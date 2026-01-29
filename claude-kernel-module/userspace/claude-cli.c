/*
 * claude-cli - Command Line Interface for Claude Kernel Module
 *
 * This tool provides a command-line interface for interacting
 * with the Claude kernel module.
 *
 * Copyright (C) 2026 Claude Code Project
 * License: GPL v2
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <signal.h>
#include "libclaude.h"

#define BUFFER_SIZE 4096

static volatile int running = 1;

static void signal_handler(int sig)
{
    (void)sig;
    running = 0;
}

static void print_usage(const char *program)
{
    printf("Claude Kernel Module CLI\n\n");
    printf("Usage: %s [OPTIONS] COMMAND [ARGS]\n\n", program);
    printf("Commands:\n");
    printf("  status        Show module status and statistics\n");
    printf("  send MESSAGE  Send a message to the kernel module\n");
    printf("  recv          Receive a message from the kernel module\n");
    printf("  monitor       Continuously monitor incoming messages\n");
    printf("  reset         Reset the module (clear buffers and stats)\n");
    printf("  flush         Flush the message buffer\n");
    printf("  mode MODE     Set operation mode (normal, debug, verbose)\n");
    printf("  version       Show version information\n");
    printf("\n");
    printf("Options:\n");
    printf("  -t, --timeout MS  Timeout for recv operations (default: 5000)\n");
    printf("  -n, --nonblock    Use non-blocking I/O\n");
    printf("  -h, --help        Show this help message\n");
    printf("\n");
    printf("Examples:\n");
    printf("  %s status                  # Show module status\n", program);
    printf("  %s send \"Hello, Claude!\"   # Send a message\n", program);
    printf("  %s recv -t 10000           # Wait for message with 10s timeout\n", program);
    printf("  %s monitor                 # Monitor incoming messages\n", program);
    printf("  %s mode debug              # Enable debug mode\n", program);
}

static void print_stats(claude_stats_t *stats)
{
    printf("Statistics:\n");
    printf("  Messages sent:     %lu\n", stats->messages_sent);
    printf("  Messages received: %lu\n", stats->messages_received);
    printf("  Bytes written:     %lu\n", stats->bytes_written);
    printf("  Bytes read:        %lu\n", stats->bytes_read);
    printf("  Errors:            %lu\n", stats->errors);
    printf("  Open count:        %lu\n", stats->open_count);
    printf("  IOCTL count:       %lu\n", stats->ioctl_count);
}

static int cmd_status(void)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    char version[32];
    claude_mode_t mode;
    claude_stats_t stats;

    printf("Claude Kernel Module Status\n");
    printf("===========================\n\n");

    if (claude_get_version(handle, version) == CLAUDE_OK) {
        printf("Module Version: %s\n", version);
    }

    printf("Library Version: %s\n", claude_lib_version());

    if (claude_get_mode(handle, &mode) == CLAUDE_OK) {
        const char *mode_str = mode == CLAUDE_MODE_NORMAL ? "normal" :
                               mode == CLAUDE_MODE_DEBUG ? "debug" : "verbose";
        printf("Operation Mode: %s\n", mode_str);
    }

    printf("\n");

    if (claude_get_stats(handle, &stats) == CLAUDE_OK) {
        print_stats(&stats);
    }

    claude_close(handle);
    return 0;
}

static int cmd_send(const char *message)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    ssize_t ret = claude_send_string(handle, message);
    if (ret < 0) {
        fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
        claude_close(handle);
        return 1;
    }

    printf("Sent %zd bytes\n", ret);
    claude_close(handle);
    return 0;
}

static int cmd_recv(int timeout_ms)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    char buffer[BUFFER_SIZE];
    ssize_t ret = claude_recv_timeout(handle, buffer, sizeof(buffer) - 1, timeout_ms);

    if (ret == CLAUDE_ERR_TIMEOUT) {
        printf("No message received (timeout)\n");
        claude_close(handle);
        return 0;
    }

    if (ret < 0) {
        fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
        claude_close(handle);
        return 1;
    }

    buffer[ret] = '\0';
    printf("Received %zd bytes: %s\n", ret, buffer);

    claude_close(handle);
    return 0;
}

static int cmd_monitor(void)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    printf("Monitoring messages (Ctrl+C to stop)...\n\n");

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    char buffer[BUFFER_SIZE];
    while (running) {
        ssize_t ret = claude_recv_timeout(handle, buffer, sizeof(buffer) - 1, 1000);

        if (ret == CLAUDE_ERR_TIMEOUT) {
            continue;
        }

        if (ret < 0) {
            if (running) {
                fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
            }
            break;
        }

        buffer[ret] = '\0';
        printf("[%zd bytes] %s\n", ret, buffer);
    }

    printf("\nMonitoring stopped.\n");
    claude_close(handle);
    return 0;
}

static int cmd_reset(void)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    int ret = claude_reset(handle);
    if (ret != CLAUDE_OK) {
        fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
        claude_close(handle);
        return 1;
    }

    printf("Module reset successfully\n");
    claude_close(handle);
    return 0;
}

static int cmd_flush(void)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    int ret = claude_flush(handle);
    if (ret != CLAUDE_OK) {
        fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
        claude_close(handle);
        return 1;
    }

    printf("Message buffer flushed\n");
    claude_close(handle);
    return 0;
}

static int cmd_mode(const char *mode_str)
{
    if (!claude_module_loaded()) {
        fprintf(stderr, "Error: Claude module is not loaded\n");
        return 1;
    }

    claude_mode_t mode;
    if (strcmp(mode_str, "normal") == 0) {
        mode = CLAUDE_MODE_NORMAL;
    } else if (strcmp(mode_str, "debug") == 0) {
        mode = CLAUDE_MODE_DEBUG;
    } else if (strcmp(mode_str, "verbose") == 0) {
        mode = CLAUDE_MODE_VERBOSE;
    } else {
        fprintf(stderr, "Error: Invalid mode '%s'\n", mode_str);
        fprintf(stderr, "Valid modes: normal, debug, verbose\n");
        return 1;
    }

    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Error: Failed to open device\n");
        return 1;
    }

    int ret = claude_set_mode(handle, mode);
    if (ret != CLAUDE_OK) {
        fprintf(stderr, "Error: %s\n", claude_strerror((claude_error_t)ret));
        claude_close(handle);
        return 1;
    }

    printf("Mode set to: %s\n", mode_str);
    claude_close(handle);
    return 0;
}

static int cmd_version(void)
{
    printf("claude-cli version %s\n", claude_lib_version());

    if (claude_module_loaded()) {
        claude_t *handle = claude_open();
        if (handle) {
            char version[32];
            if (claude_get_version(handle, version) == CLAUDE_OK) {
                printf("Kernel module version %s\n", version);
            }
            claude_close(handle);
        }
    } else {
        printf("Kernel module: not loaded\n");
    }

    return 0;
}

int main(int argc, char *argv[])
{
    int timeout_ms = 5000;
    int nonblock = 0;

    static struct option long_options[] = {
        {"timeout", required_argument, 0, 't'},
        {"nonblock", no_argument, 0, 'n'},
        {"help", no_argument, 0, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "t:nh", long_options, NULL)) != -1) {
        switch (opt) {
        case 't':
            timeout_ms = atoi(optarg);
            break;
        case 'n':
            nonblock = 1;
            break;
        case 'h':
            print_usage(argv[0]);
            return 0;
        default:
            print_usage(argv[0]);
            return 1;
        }
    }

    (void)nonblock; /* Reserved for future use */

    if (optind >= argc) {
        print_usage(argv[0]);
        return 1;
    }

    const char *command = argv[optind];

    if (strcmp(command, "status") == 0) {
        return cmd_status();
    } else if (strcmp(command, "send") == 0) {
        if (optind + 1 >= argc) {
            fprintf(stderr, "Error: send command requires a message\n");
            return 1;
        }
        return cmd_send(argv[optind + 1]);
    } else if (strcmp(command, "recv") == 0) {
        return cmd_recv(timeout_ms);
    } else if (strcmp(command, "monitor") == 0) {
        return cmd_monitor();
    } else if (strcmp(command, "reset") == 0) {
        return cmd_reset();
    } else if (strcmp(command, "flush") == 0) {
        return cmd_flush();
    } else if (strcmp(command, "mode") == 0) {
        if (optind + 1 >= argc) {
            fprintf(stderr, "Error: mode command requires a mode argument\n");
            return 1;
        }
        return cmd_mode(argv[optind + 1]);
    } else if (strcmp(command, "version") == 0) {
        return cmd_version();
    } else {
        fprintf(stderr, "Error: Unknown command '%s'\n", command);
        print_usage(argv[0]);
        return 1;
    }
}
