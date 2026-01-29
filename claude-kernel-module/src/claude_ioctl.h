/*
 * Claude Kernel Module - IOCTL Interface Header
 *
 * This header defines the IOCTL commands and structures for
 * communicating with the Claude kernel module from userspace.
 *
 * Copyright (C) 2026 Claude Code Project
 * License: GPL v2
 */

#ifndef _CLAUDE_IOCTL_H
#define _CLAUDE_IOCTL_H

#include <linux/ioctl.h>

/* IOCTL magic number */
#define CLAUDE_IOC_MAGIC 'C'

/* Statistics structure - shared between kernel and userspace */
struct claude_stats {
    unsigned long messages_sent;
    unsigned long messages_received;
    unsigned long bytes_written;
    unsigned long bytes_read;
    unsigned long errors;
    unsigned long open_count;
    unsigned long ioctl_count;
};

/* Operation modes */
#define CLAUDE_MODE_NORMAL    0   /* Normal operation */
#define CLAUDE_MODE_DEBUG     1   /* Debug logging enabled */
#define CLAUDE_MODE_VERBOSE   2   /* Verbose logging enabled */

/*
 * IOCTL Commands
 */

/* Reset the device - clears buffers and statistics */
#define CLAUDE_IOC_RESET      _IO(CLAUDE_IOC_MAGIC, 0)

/* Get statistics */
#define CLAUDE_IOC_GET_STATS  _IOR(CLAUDE_IOC_MAGIC, 1, struct claude_stats)

/* Set operation mode */
#define CLAUDE_IOC_SET_MODE   _IOW(CLAUDE_IOC_MAGIC, 2, int)

/* Get current operation mode */
#define CLAUDE_IOC_GET_MODE   _IOR(CLAUDE_IOC_MAGIC, 3, int)

/* Flush the message buffer */
#define CLAUDE_IOC_FLUSH      _IO(CLAUDE_IOC_MAGIC, 4)

/* Get module version string */
#define CLAUDE_IOC_GET_VERSION _IOR(CLAUDE_IOC_MAGIC, 5, char[32])

/* Device path */
#define CLAUDE_DEVICE_PATH "/dev/claude"

/* Proc status path */
#define CLAUDE_PROC_PATH "/proc/claude_status"

#endif /* _CLAUDE_IOCTL_H */
