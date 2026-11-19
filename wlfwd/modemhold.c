/*
 * Hold the modem processor's node open, which is what keeps it running.
 *
 * The open is tried whether or not the subsystem says it is ready: on a cold
 * boot the state reads OFFLINING and never settles by itself, and the open is
 * exactly what starts it.  A failed open is reported with its errno, because
 * the reason (no firmware, or a boot still winding down) is not in the log
 * otherwise.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void report(const char *what, int err)
{
	char line[192];
	int len;
	int fd;

	len = snprintf(line, sizeof(line), "modemhold: %s%s%s\n",
		       what, err ? ": " : "", err ? strerror(err) : "");

	fd = open("/dev/kmsg", O_WRONLY);
	if (fd >= 0) {
		write(fd, line, len);
		close(fd);
	}

	fputs(line, stdout);
	fflush(stdout);
}

int main(void)
{
	int fd;
	int err;
	int tries;

	for (tries = 0; tries < 600; tries++) {
		fd = open("/dev/subsys_modem", O_RDONLY);
		if (fd >= 0) {
			report("modem opened, holding", 0);
			for (;;)
				pause();
		}

		err = errno;
		if (tries == 0 || tries % 10 == 9)
			report("open failed", err);
		sleep(1);
	}

	report("gave up waiting for the modem", 0);
	return 1;
}
