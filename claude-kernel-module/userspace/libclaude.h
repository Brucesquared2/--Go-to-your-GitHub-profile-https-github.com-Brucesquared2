/*
 * libclaude - Userspace Library for Claude Kernel Module
 *
 * This library provides a C API for interacting with the
 * Claude kernel module from userspace applications.
 *
 * Copyright (C) 2026 Claude Code Project
 * License: GPL v2
 */

#ifndef _LIBCLAUDE_H
#define _LIBCLAUDE_H

#include <stdint.h>
#include <stdbool.h>
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Version */
#define LIBCLAUDE_VERSION "1.0.0"

/* Operation modes */
typedef enum {
    CLAUDE_MODE_NORMAL  = 0,
    CLAUDE_MODE_DEBUG   = 1,
    CLAUDE_MODE_VERBOSE = 2
} claude_mode_t;

/* Statistics structure */
typedef struct {
    unsigned long messages_sent;
    unsigned long messages_received;
    unsigned long bytes_written;
    unsigned long bytes_read;
    unsigned long errors;
    unsigned long open_count;
    unsigned long ioctl_count;
} claude_stats_t;

/* Error codes */
typedef enum {
    CLAUDE_OK = 0,
    CLAUDE_ERR_OPEN = -1,
    CLAUDE_ERR_CLOSE = -2,
    CLAUDE_ERR_READ = -3,
    CLAUDE_ERR_WRITE = -4,
    CLAUDE_ERR_IOCTL = -5,
    CLAUDE_ERR_INVALID = -6,
    CLAUDE_ERR_TIMEOUT = -7,
    CLAUDE_ERR_BUSY = -8,
    CLAUDE_ERR_NOMEM = -9,
    CLAUDE_ERR_PERM = -10
} claude_error_t;

/* Claude handle */
typedef struct claude_handle claude_t;

/*
 * Connection Management
 */

/**
 * Open a connection to the Claude kernel module.
 *
 * @return Handle on success, NULL on failure
 */
claude_t *claude_open(void);

/**
 * Open a connection with non-blocking mode.
 *
 * @return Handle on success, NULL on failure
 */
claude_t *claude_open_nonblock(void);

/**
 * Close the connection.
 *
 * @param handle The Claude handle
 */
void claude_close(claude_t *handle);

/**
 * Check if connection is open.
 *
 * @param handle The Claude handle
 * @return true if connected, false otherwise
 */
bool claude_is_open(claude_t *handle);

/*
 * Message Operations
 */

/**
 * Send a message to the kernel module.
 *
 * @param handle The Claude handle
 * @param data   Data to send
 * @param len    Length of data
 * @return Number of bytes written, or negative error code
 */
ssize_t claude_send(claude_t *handle, const void *data, size_t len);

/**
 * Send a string message.
 *
 * @param handle  The Claude handle
 * @param message Null-terminated string
 * @return Number of bytes written, or negative error code
 */
ssize_t claude_send_string(claude_t *handle, const char *message);

/**
 * Receive a message from the kernel module.
 *
 * @param handle The Claude handle
 * @param buf    Buffer to store received data
 * @param len    Maximum bytes to receive
 * @return Number of bytes read, or negative error code
 */
ssize_t claude_recv(claude_t *handle, void *buf, size_t len);

/**
 * Receive with timeout.
 *
 * @param handle     The Claude handle
 * @param buf        Buffer to store received data
 * @param len        Maximum bytes to receive
 * @param timeout_ms Timeout in milliseconds (-1 for infinite)
 * @return Number of bytes read, or negative error code
 */
ssize_t claude_recv_timeout(claude_t *handle, void *buf, size_t len, int timeout_ms);

/**
 * Check if data is available to read.
 *
 * @param handle The Claude handle
 * @return true if data available, false otherwise
 */
bool claude_data_available(claude_t *handle);

/*
 * Control Operations
 */

/**
 * Reset the device.
 *
 * @param handle The Claude handle
 * @return 0 on success, negative error code on failure
 */
int claude_reset(claude_t *handle);

/**
 * Flush the message buffer.
 *
 * @param handle The Claude handle
 * @return 0 on success, negative error code on failure
 */
int claude_flush(claude_t *handle);

/**
 * Set operation mode.
 *
 * @param handle The Claude handle
 * @param mode   The operation mode
 * @return 0 on success, negative error code on failure
 */
int claude_set_mode(claude_t *handle, claude_mode_t mode);

/**
 * Get current operation mode.
 *
 * @param handle The Claude handle
 * @param mode   Pointer to store mode
 * @return 0 on success, negative error code on failure
 */
int claude_get_mode(claude_t *handle, claude_mode_t *mode);

/*
 * Information Retrieval
 */

/**
 * Get statistics.
 *
 * @param handle The Claude handle
 * @param stats  Pointer to store statistics
 * @return 0 on success, negative error code on failure
 */
int claude_get_stats(claude_t *handle, claude_stats_t *stats);

/**
 * Get module version.
 *
 * @param handle  The Claude handle
 * @param version Buffer to store version string (min 32 bytes)
 * @return 0 on success, negative error code on failure
 */
int claude_get_version(claude_t *handle, char *version);

/**
 * Get the file descriptor (for advanced use).
 *
 * @param handle The Claude handle
 * @return File descriptor, or -1 if not open
 */
int claude_get_fd(claude_t *handle);

/*
 * Utility Functions
 */

/**
 * Get error message for error code.
 *
 * @param error The error code
 * @return Error message string
 */
const char *claude_strerror(claude_error_t error);

/**
 * Get library version.
 *
 * @return Version string
 */
const char *claude_lib_version(void);

/**
 * Check if kernel module is loaded.
 *
 * @return true if module is loaded, false otherwise
 */
bool claude_module_loaded(void);

#ifdef __cplusplus
}
#endif

#endif /* _LIBCLAUDE_H */
