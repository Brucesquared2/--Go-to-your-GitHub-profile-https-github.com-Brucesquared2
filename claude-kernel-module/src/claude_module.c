/*
 * Claude Code Linux Kernel Module
 *
 * This kernel module provides a character device interface (/dev/claude)
 * that enables kernel-level integration for Claude Code operations.
 *
 * Features:
 * - Character device for userspace communication
 * - IOCTL interface for control commands
 * - Procfs interface for status monitoring
 * - Ring buffer for message queuing
 *
 * Copyright (C) 2026 Claude Code Project
 * License: GPL v2
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/mutex.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/kfifo.h>
#include <linux/wait.h>
#include <linux/poll.h>
#include <linux/ioctl.h>
#include <linux/version.h>

#define DEVICE_NAME "claude"
#define CLASS_NAME "claude_class"
#define PROC_NAME "claude_status"

/* Module version */
#define CLAUDE_MODULE_VERSION "1.0.0"

/* Buffer sizes */
#define CLAUDE_BUFFER_SIZE 4096
#define CLAUDE_FIFO_SIZE 8192

/* IOCTL commands */
#define CLAUDE_IOC_MAGIC 'C'
#define CLAUDE_IOC_RESET      _IO(CLAUDE_IOC_MAGIC, 0)
#define CLAUDE_IOC_GET_STATS  _IOR(CLAUDE_IOC_MAGIC, 1, struct claude_stats)
#define CLAUDE_IOC_SET_MODE   _IOW(CLAUDE_IOC_MAGIC, 2, int)
#define CLAUDE_IOC_GET_MODE   _IOR(CLAUDE_IOC_MAGIC, 3, int)
#define CLAUDE_IOC_FLUSH      _IO(CLAUDE_IOC_MAGIC, 4)
#define CLAUDE_IOC_GET_VERSION _IOR(CLAUDE_IOC_MAGIC, 5, char[32])

/* Operation modes */
#define CLAUDE_MODE_NORMAL    0
#define CLAUDE_MODE_DEBUG     1
#define CLAUDE_MODE_VERBOSE   2

/* Statistics structure */
struct claude_stats {
    unsigned long messages_sent;
    unsigned long messages_received;
    unsigned long bytes_written;
    unsigned long bytes_read;
    unsigned long errors;
    unsigned long open_count;
    unsigned long ioctl_count;
};

/* Module state */
static struct {
    dev_t dev_num;
    struct cdev cdev;
    struct class *class;
    struct device *device;
    struct proc_dir_entry *proc_entry;

    /* Synchronization */
    struct mutex lock;
    wait_queue_head_t read_queue;
    wait_queue_head_t write_queue;

    /* Data buffers */
    DECLARE_KFIFO(msg_fifo, unsigned char, CLAUDE_FIFO_SIZE);

    /* Statistics */
    struct claude_stats stats;

    /* Configuration */
    int mode;
    bool initialized;
} claude_dev;

/* Forward declarations */
static int claude_open(struct inode *inode, struct file *filp);
static int claude_release(struct inode *inode, struct file *filp);
static ssize_t claude_read(struct file *filp, char __user *buf, size_t count, loff_t *f_pos);
static ssize_t claude_write(struct file *filp, const char __user *buf, size_t count, loff_t *f_pos);
static long claude_ioctl(struct file *filp, unsigned int cmd, unsigned long arg);
static unsigned int claude_poll(struct file *filp, poll_table *wait);

/* File operations structure */
static const struct file_operations claude_fops = {
    .owner          = THIS_MODULE,
    .open           = claude_open,
    .release        = claude_release,
    .read           = claude_read,
    .write          = claude_write,
    .unlocked_ioctl = claude_ioctl,
    .poll           = claude_poll,
};

/*
 * Open handler - called when userspace opens /dev/claude
 */
static int claude_open(struct inode *inode, struct file *filp)
{
    mutex_lock(&claude_dev.lock);
    claude_dev.stats.open_count++;

    if (claude_dev.mode == CLAUDE_MODE_DEBUG ||
        claude_dev.mode == CLAUDE_MODE_VERBOSE) {
        pr_info("claude: device opened (count: %lu)\n",
                claude_dev.stats.open_count);
    }

    mutex_unlock(&claude_dev.lock);
    return 0;
}

/*
 * Release handler - called when userspace closes the device
 */
static int claude_release(struct inode *inode, struct file *filp)
{
    if (claude_dev.mode == CLAUDE_MODE_DEBUG ||
        claude_dev.mode == CLAUDE_MODE_VERBOSE) {
        pr_info("claude: device closed\n");
    }
    return 0;
}

/*
 * Read handler - read messages from the kernel buffer
 */
static ssize_t claude_read(struct file *filp, char __user *buf,
                          size_t count, loff_t *f_pos)
{
    unsigned int copied;
    int ret;

    if (mutex_lock_interruptible(&claude_dev.lock))
        return -ERESTARTSYS;

    /* Wait for data if FIFO is empty and non-blocking not set */
    while (kfifo_is_empty(&claude_dev.msg_fifo)) {
        mutex_unlock(&claude_dev.lock);

        if (filp->f_flags & O_NONBLOCK)
            return -EAGAIN;

        if (wait_event_interruptible(claude_dev.read_queue,
                                     !kfifo_is_empty(&claude_dev.msg_fifo)))
            return -ERESTARTSYS;

        if (mutex_lock_interruptible(&claude_dev.lock))
            return -ERESTARTSYS;
    }

    /* Copy data to userspace */
    ret = kfifo_to_user(&claude_dev.msg_fifo, buf, count, &copied);
    if (ret) {
        mutex_unlock(&claude_dev.lock);
        return ret;
    }

    claude_dev.stats.bytes_read += copied;
    claude_dev.stats.messages_received++;

    if (claude_dev.mode == CLAUDE_MODE_VERBOSE) {
        pr_info("claude: read %u bytes\n", copied);
    }

    mutex_unlock(&claude_dev.lock);

    /* Wake up writers */
    wake_up_interruptible(&claude_dev.write_queue);

    return copied;
}

/*
 * Write handler - write messages to the kernel buffer
 */
static ssize_t claude_write(struct file *filp, const char __user *buf,
                           size_t count, loff_t *f_pos)
{
    unsigned int copied;
    int ret;

    if (count > CLAUDE_BUFFER_SIZE)
        count = CLAUDE_BUFFER_SIZE;

    if (mutex_lock_interruptible(&claude_dev.lock))
        return -ERESTARTSYS;

    /* Wait for space if FIFO is full and non-blocking not set */
    while (kfifo_avail(&claude_dev.msg_fifo) < count) {
        mutex_unlock(&claude_dev.lock);

        if (filp->f_flags & O_NONBLOCK)
            return -EAGAIN;

        if (wait_event_interruptible(claude_dev.write_queue,
                                     kfifo_avail(&claude_dev.msg_fifo) >= count))
            return -ERESTARTSYS;

        if (mutex_lock_interruptible(&claude_dev.lock))
            return -ERESTARTSYS;
    }

    /* Copy data from userspace */
    ret = kfifo_from_user(&claude_dev.msg_fifo, buf, count, &copied);
    if (ret) {
        claude_dev.stats.errors++;
        mutex_unlock(&claude_dev.lock);
        return ret;
    }

    claude_dev.stats.bytes_written += copied;
    claude_dev.stats.messages_sent++;

    if (claude_dev.mode == CLAUDE_MODE_VERBOSE) {
        pr_info("claude: wrote %u bytes\n", copied);
    }

    mutex_unlock(&claude_dev.lock);

    /* Wake up readers */
    wake_up_interruptible(&claude_dev.read_queue);

    return copied;
}

/*
 * IOCTL handler - handle control commands
 */
static long claude_ioctl(struct file *filp, unsigned int cmd, unsigned long arg)
{
    int ret = 0;
    int mode;
    char version[32];

    mutex_lock(&claude_dev.lock);
    claude_dev.stats.ioctl_count++;

    switch (cmd) {
    case CLAUDE_IOC_RESET:
        /* Reset the FIFO and statistics */
        kfifo_reset(&claude_dev.msg_fifo);
        memset(&claude_dev.stats, 0, sizeof(claude_dev.stats));
        pr_info("claude: device reset\n");
        break;

    case CLAUDE_IOC_GET_STATS:
        if (copy_to_user((void __user *)arg, &claude_dev.stats,
                        sizeof(struct claude_stats))) {
            ret = -EFAULT;
        }
        break;

    case CLAUDE_IOC_SET_MODE:
        if (copy_from_user(&mode, (void __user *)arg, sizeof(int))) {
            ret = -EFAULT;
        } else if (mode < CLAUDE_MODE_NORMAL || mode > CLAUDE_MODE_VERBOSE) {
            ret = -EINVAL;
        } else {
            claude_dev.mode = mode;
            pr_info("claude: mode set to %d\n", mode);
        }
        break;

    case CLAUDE_IOC_GET_MODE:
        if (copy_to_user((void __user *)arg, &claude_dev.mode, sizeof(int))) {
            ret = -EFAULT;
        }
        break;

    case CLAUDE_IOC_FLUSH:
        kfifo_reset(&claude_dev.msg_fifo);
        wake_up_interruptible(&claude_dev.write_queue);
        pr_info("claude: FIFO flushed\n");
        break;

    case CLAUDE_IOC_GET_VERSION:
        strncpy(version, CLAUDE_MODULE_VERSION, sizeof(version) - 1);
        version[sizeof(version) - 1] = '\0';
        if (copy_to_user((void __user *)arg, version, sizeof(version))) {
            ret = -EFAULT;
        }
        break;

    default:
        ret = -ENOTTY;
        break;
    }

    mutex_unlock(&claude_dev.lock);
    return ret;
}

/*
 * Poll handler - for select/poll/epoll support
 */
static unsigned int claude_poll(struct file *filp, poll_table *wait)
{
    unsigned int mask = 0;

    mutex_lock(&claude_dev.lock);

    poll_wait(filp, &claude_dev.read_queue, wait);
    poll_wait(filp, &claude_dev.write_queue, wait);

    /* Check if readable */
    if (!kfifo_is_empty(&claude_dev.msg_fifo))
        mask |= POLLIN | POLLRDNORM;

    /* Check if writable */
    if (kfifo_avail(&claude_dev.msg_fifo) > 0)
        mask |= POLLOUT | POLLWRNORM;

    mutex_unlock(&claude_dev.lock);

    return mask;
}

/*
 * Procfs show handler - display status information
 */
static int claude_proc_show(struct seq_file *m, void *v)
{
    mutex_lock(&claude_dev.lock);

    seq_printf(m, "Claude Kernel Module Status\n");
    seq_printf(m, "===========================\n\n");
    seq_printf(m, "Version: %s\n", CLAUDE_MODULE_VERSION);
    seq_printf(m, "Mode: %d (%s)\n", claude_dev.mode,
               claude_dev.mode == CLAUDE_MODE_NORMAL ? "normal" :
               claude_dev.mode == CLAUDE_MODE_DEBUG ? "debug" : "verbose");
    seq_printf(m, "\nStatistics:\n");
    seq_printf(m, "  Messages sent:     %lu\n", claude_dev.stats.messages_sent);
    seq_printf(m, "  Messages received: %lu\n", claude_dev.stats.messages_received);
    seq_printf(m, "  Bytes written:     %lu\n", claude_dev.stats.bytes_written);
    seq_printf(m, "  Bytes read:        %lu\n", claude_dev.stats.bytes_read);
    seq_printf(m, "  Errors:            %lu\n", claude_dev.stats.errors);
    seq_printf(m, "  Open count:        %lu\n", claude_dev.stats.open_count);
    seq_printf(m, "  IOCTL count:       %lu\n", claude_dev.stats.ioctl_count);
    seq_printf(m, "\nBuffer Status:\n");
    seq_printf(m, "  FIFO size:         %u\n", kfifo_size(&claude_dev.msg_fifo));
    seq_printf(m, "  FIFO used:         %u\n", kfifo_len(&claude_dev.msg_fifo));
    seq_printf(m, "  FIFO available:    %u\n", kfifo_avail(&claude_dev.msg_fifo));

    mutex_unlock(&claude_dev.lock);

    return 0;
}

static int claude_proc_open(struct inode *inode, struct file *file)
{
    return single_open(file, claude_proc_show, NULL);
}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 6, 0)
static const struct proc_ops claude_proc_ops = {
    .proc_open    = claude_proc_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};
#else
static const struct file_operations claude_proc_ops = {
    .owner   = THIS_MODULE,
    .open    = claude_proc_open,
    .read    = seq_read,
    .llseek  = seq_lseek,
    .release = single_release,
};
#endif

/*
 * Module initialization
 */
static int __init claude_init(void)
{
    int ret;

    pr_info("claude: Initializing Claude Kernel Module v%s\n",
            CLAUDE_MODULE_VERSION);

    /* Initialize state */
    memset(&claude_dev, 0, sizeof(claude_dev));
    mutex_init(&claude_dev.lock);
    init_waitqueue_head(&claude_dev.read_queue);
    init_waitqueue_head(&claude_dev.write_queue);
    INIT_KFIFO(claude_dev.msg_fifo);
    claude_dev.mode = CLAUDE_MODE_NORMAL;

    /* Allocate device number */
    ret = alloc_chrdev_region(&claude_dev.dev_num, 0, 1, DEVICE_NAME);
    if (ret < 0) {
        pr_err("claude: Failed to allocate device number\n");
        return ret;
    }

    /* Initialize cdev */
    cdev_init(&claude_dev.cdev, &claude_fops);
    claude_dev.cdev.owner = THIS_MODULE;

    ret = cdev_add(&claude_dev.cdev, claude_dev.dev_num, 1);
    if (ret < 0) {
        pr_err("claude: Failed to add cdev\n");
        goto err_unregister;
    }

    /* Create device class */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 4, 0)
    claude_dev.class = class_create(CLASS_NAME);
#else
    claude_dev.class = class_create(THIS_MODULE, CLASS_NAME);
#endif
    if (IS_ERR(claude_dev.class)) {
        pr_err("claude: Failed to create device class\n");
        ret = PTR_ERR(claude_dev.class);
        goto err_cdev;
    }

    /* Create device */
    claude_dev.device = device_create(claude_dev.class, NULL,
                                      claude_dev.dev_num, NULL, DEVICE_NAME);
    if (IS_ERR(claude_dev.device)) {
        pr_err("claude: Failed to create device\n");
        ret = PTR_ERR(claude_dev.device);
        goto err_class;
    }

    /* Create proc entry */
    claude_dev.proc_entry = proc_create(PROC_NAME, 0444, NULL, &claude_proc_ops);
    if (!claude_dev.proc_entry) {
        pr_warn("claude: Failed to create proc entry (non-fatal)\n");
    }

    claude_dev.initialized = true;

    pr_info("claude: Module loaded successfully\n");
    pr_info("claude: Device: /dev/%s (major: %d, minor: %d)\n",
            DEVICE_NAME, MAJOR(claude_dev.dev_num), MINOR(claude_dev.dev_num));
    pr_info("claude: Status: /proc/%s\n", PROC_NAME);

    return 0;

err_class:
    class_destroy(claude_dev.class);
err_cdev:
    cdev_del(&claude_dev.cdev);
err_unregister:
    unregister_chrdev_region(claude_dev.dev_num, 1);
    return ret;
}

/*
 * Module cleanup
 */
static void __exit claude_exit(void)
{
    pr_info("claude: Unloading module\n");

    if (claude_dev.proc_entry)
        proc_remove(claude_dev.proc_entry);

    if (claude_dev.device)
        device_destroy(claude_dev.class, claude_dev.dev_num);

    if (claude_dev.class)
        class_destroy(claude_dev.class);

    cdev_del(&claude_dev.cdev);
    unregister_chrdev_region(claude_dev.dev_num, 1);

    pr_info("claude: Module unloaded\n");
}

module_init(claude_init);
module_exit(claude_exit);

MODULE_LICENSE("GPL v2");
MODULE_AUTHOR("Claude Code Project");
MODULE_DESCRIPTION("Claude Code Linux Kernel Module - Kernel-level integration interface");
MODULE_VERSION(CLAUDE_MODULE_VERSION);
