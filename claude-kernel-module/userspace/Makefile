# Claude Kernel Module - Userspace Tools Makefile
#
# Builds the userspace library and command-line tool.
#
# Usage:
#   make          - Build all userspace tools
#   make clean    - Clean build artifacts
#   make install  - Install library and CLI tool

CC ?= gcc
CFLAGS = -Wall -Wextra -O2 -fPIC
LDFLAGS = -L. -lclaude

# Library
LIB_NAME = libclaude
LIB_SRC = libclaude.c
LIB_OBJ = $(LIB_SRC:.c=.o)
LIB_STATIC = $(LIB_NAME).a
LIB_SHARED = $(LIB_NAME).so.1.0.0
LIB_SONAME = $(LIB_NAME).so.1
LIB_LINK = $(LIB_NAME).so

# CLI Tool
CLI_NAME = claude-cli
CLI_SRC = claude-cli.c
CLI_OBJ = $(CLI_SRC:.c=.o)

# Installation directories
PREFIX ?= /usr/local
LIBDIR = $(PREFIX)/lib
BINDIR = $(PREFIX)/bin
INCLUDEDIR = $(PREFIX)/include

.PHONY: all clean install uninstall

all: $(LIB_STATIC) $(LIB_SHARED) $(CLI_NAME)

# Static library
$(LIB_STATIC): $(LIB_OBJ)
	ar rcs $@ $^

# Shared library
$(LIB_SHARED): $(LIB_OBJ)
	$(CC) -shared -Wl,-soname,$(LIB_SONAME) -o $@ $^
	ln -sf $(LIB_SHARED) $(LIB_SONAME)
	ln -sf $(LIB_SONAME) $(LIB_LINK)

# CLI tool
$(CLI_NAME): $(CLI_OBJ) $(LIB_STATIC)
	$(CC) -o $@ $(CLI_OBJ) $(LIB_STATIC)

# Object files
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# Clean
clean:
	rm -f $(LIB_OBJ) $(CLI_OBJ)
	rm -f $(LIB_STATIC) $(LIB_SHARED) $(LIB_SONAME) $(LIB_LINK)
	rm -f $(CLI_NAME)

# Install
install: all
	install -d $(DESTDIR)$(LIBDIR)
	install -d $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(INCLUDEDIR)/claude
	install -m 644 $(LIB_STATIC) $(DESTDIR)$(LIBDIR)/
	install -m 755 $(LIB_SHARED) $(DESTDIR)$(LIBDIR)/
	ln -sf $(LIB_SHARED) $(DESTDIR)$(LIBDIR)/$(LIB_SONAME)
	ln -sf $(LIB_SONAME) $(DESTDIR)$(LIBDIR)/$(LIB_LINK)
	install -m 755 $(CLI_NAME) $(DESTDIR)$(BINDIR)/
	install -m 644 libclaude.h $(DESTDIR)$(INCLUDEDIR)/claude/
	ldconfig || true

# Uninstall
uninstall:
	rm -f $(DESTDIR)$(LIBDIR)/$(LIB_STATIC)
	rm -f $(DESTDIR)$(LIBDIR)/$(LIB_SHARED)
	rm -f $(DESTDIR)$(LIBDIR)/$(LIB_SONAME)
	rm -f $(DESTDIR)$(LIBDIR)/$(LIB_LINK)
	rm -f $(DESTDIR)$(BINDIR)/$(CLI_NAME)
	rm -rf $(DESTDIR)$(INCLUDEDIR)/claude
	ldconfig || true
