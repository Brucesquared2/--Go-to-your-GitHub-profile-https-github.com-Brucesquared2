/*
 * libclaude - Userspace Library Implementation
 *
 * Copyright (C) 2026 Claude Code Project
 * License: GPL v2
 */

#include "libclaude.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/poll.h>
#include <sys/stat.h>
#include <linux/ioctl.h>

/* Device path */
#define CLAUDE_DEVICE_PATH "/dev/claude"
#define CLAUDE_PROC_PATH "/proc/claude_status"

/* IOCTL definitions (must match kernel module) */
#define CLAUDE_IOC_MAGIC 'C'
#define CLAUDE_IOC_RESET      _IO(CLAUDE_IOC_MAGIC, 0)
#define CLAUDE_IOC_GET_STATS  _IOR(CLAUDE_IOC_MAGIC, 1, claude_stats_t)
#define CLAUDE_IOC_SET_MODE   _IOW(CLAUDE_IOC_MAGIC, 2, int)
#define CLAUDE_IOC_GET_MODE   _IOR(CLAUDE_IOC_MAGIC, 3, int)
#define CLAUDE_IOC_FLUSH      _IO(CLAUDE_IOC_MAGIC, 4)
#define CLAUDE_IOC_GET_VERSION _IOR(CLAUDE_IOC_MAGIC, 5, char[32])

/* Internal handle structure */
struct claude_handle {
    int fd;
    bool nonblock;
};

/*
 * Connection Management
 */

static claude_t *claude_open_internal(int flags)
{
    claude_t *handle = malloc(sizeof(claude_t));
    if (!handle) {
        return NULL;
    }

    handle->fd = open(CLAUDE_DEVICE_PATH, flags);
    if (handle->fd < 0) {
        free(handle);
        return NULL;
    }

    handle->nonblock = (flags & O_NONBLOCK) != 0;
    return handle;
}

claude_t *claude_open(void)
{
    return claude_open_internal(O_RDWR);
}

claude_t *claude_open_nonblock(void)
{
    return claude_open_internal(O_RDWR | O_NONBLOCK);
}

void claude_close(claude_t *handle)
{
    if (handle) {
        if (handle->fd >= 0) {
            close(handle->fd);
        }
        free(handle);
    }
}

bool claude_is_open(claude_t *handle)
{
    return handle && handle->fd >= 0;
}

/*
 * Message Operations
 */

ssize_t claude_send(claude_t *handle, const void *data, size_t len)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    if (!data || len == 0) {
        return CLAUDE_ERR_INVALID;
    }

    ssize_t ret = write(handle->fd, data, len);
    if (ret < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return CLAUDE_ERR_BUSY;
        }
        return CLAUDE_ERR_WRITE;
    }

    return ret;
}

ssize_t claude_send_string(claude_t *handle, const char *message)
{
    if (!message) {
        return CLAUDE_ERR_INVALID;
    }
    return claude_send(handle, message, strlen(message) + 1);
}

ssize_t claude_recv(claude_t *handle, void *buf, size_t len)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    if (!buf || len == 0) {
        return CLAUDE_ERR_INVALID;
    }

    ssize_t ret = read(handle->fd, buf, len);
    if (ret < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return CLAUDE_ERR_BUSY;
        }
        return CLAUDE_ERR_READ;
    }

    return ret;
}

ssize_t claude_recv_timeout(claude_t *handle, void *buf, size_t len, int timeout_ms)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    struct pollfd pfd;
    pfd.fd = handle->fd;
    pfd.events = POLLIN;

    int ret = poll(&pfd, 1, timeout_ms);
    if (ret < 0) {
        return CLAUDE_ERR_READ;
    }
    if (ret == 0) {
        return CLAUDE_ERR_TIMEOUT;
    }

    if (pfd.revents & POLLIN) {
        return claude_recv(handle, buf, len);
    }

    return CLAUDE_ERR_READ;
}

bool claude_data_available(claude_t *handle)
{
    if (!handle || handle->fd < 0) {
        return false;
    }

    struct pollfd pfd;
    pfd.fd = handle->fd;
    pfd.events = POLLIN;

    int ret = poll(&pfd, 1, 0);
    return ret > 0 && (pfd.revents & POLLIN);
}

/*
 * Control Operations
 */

int claude_reset(claude_t *handle)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    if (ioctl(handle->fd, CLAUDE_IOC_RESET) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    return CLAUDE_OK;
}

int claude_flush(claude_t *handle)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    if (ioctl(handle->fd, CLAUDE_IOC_FLUSH) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    return CLAUDE_OK;
}

int claude_set_mode(claude_t *handle, claude_mode_t mode)
{
    if (!handle || handle->fd < 0) {
        return CLAUDE_ERR_INVALID;
    }

    int m = (int)mode;
    if (ioctl(handle->fd, CLAUDE_IOC_SET_MODE, &m) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    return CLAUDE_OK;
}

int claude_get_mode(claude_t *handle, claude_mode_t *mode)
{
    if (!handle || handle->fd < 0 || !mode) {
        return CLAUDE_ERR_INVALID;
    }

    int m;
    if (ioctl(handle->fd, CLAUDE_IOC_GET_MODE, &m) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    *mode = (claude_mode_t)m;
    return CLAUDE_OK;
}

/*
 * Information Retrieval
 */

int claude_get_stats(claude_t *handle, claude_stats_t *stats)
{
    if (!handle || handle->fd < 0 || !stats) {
        return CLAUDE_ERR_INVALID;
    }

    if (ioctl(handle->fd, CLAUDE_IOC_GET_STATS, stats) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    return CLAUDE_OK;
}

int claude_get_version(claude_t *handle, char *version)
{
    if (!handle || handle->fd < 0 || !version) {
        return CLAUDE_ERR_INVALID;
    }

    if (ioctl(handle->fd, CLAUDE_IOC_GET_VERSION, version) < 0) {
        return CLAUDE_ERR_IOCTL;
    }

    return CLAUDE_OK;
}

int claude_get_fd(claude_t *handle)
{
    if (!handle) {
        return -1;
    }
    return handle->fd;
}

/*
 * Utility Functions
 */

const char *claude_strerror(claude_error_t error)
{
    switch (error) {
    case CLAUDE_OK:
        return "Success";
    case CLAUDE_ERR_OPEN:
        return "Failed to open device";
    case CLAUDE_ERR_CLOSE:
        return "Failed to close device";
    case CLAUDE_ERR_READ:
        return "Read error";
    case CLAUDE_ERR_WRITE:
        return "Write error";
    case CLAUDE_ERR_IOCTL:
        return "IOCTL error";
    case CLAUDE_ERR_INVALID:
        return "Invalid argument";
    case CLAUDE_ERR_TIMEOUT:
        return "Operation timed out";
    case CLAUDE_ERR_BUSY:
        return "Resource busy";
    case CLAUDE_ERR_NOMEM:
        return "Out of memory";
    case CLAUDE_ERR_PERM:
        return "Permission denied";
    default:
        return "Unknown error";
    }
}

const char *claude_lib_version(void)
{
    return LIBCLAUDE_VERSION;
}

bool claude_module_loaded(void)
{
    struct stat st;
    return stat(CLAUDE_DEVICE_PATH, &st) == 0 && S_ISCHR(st.st_mode);
}
