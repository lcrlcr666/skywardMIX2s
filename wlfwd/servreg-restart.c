// servreg-restart: ask the servreg notification service to restart a
// protection domain, with the QMI encoding the service actually expects.
//
// The earlier pdr-restart sent the name without the one-byte length a QMI
// string carries, and always sent an "enable" TLV that a restart request does
// not have; the modem answered "malformed" and nothing happened.  This sends
// the request the way drivers/soc/qcom/service-notifier.c builds it.
//
// Usage: servreg-restart <node> <port> <pd name>
#include <sys/socket.h>
#include <sys/time.h>
#include <linux/qrtr.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef AF_QIPCRTR
#define AF_QIPCRTR 42
#endif

#define SERVREG_NOTIF_RESTART_PD 0x0024

int main(int argc, char **argv)
{
	struct sockaddr_qrtr srv = { .sq_family = AF_QIPCRTR };
	struct timeval tv = { .tv_sec = 5 };
	uint8_t buf[512], resp[512];
	size_t len;
	ssize_t n;
	int sock;
	int off;

	if (argc != 4) {
		fprintf(stderr, "usage: %s <node> <port> <pd name>\n", argv[0]);
		return 1;
	}
	len = strlen(argv[3]);
	srv.sq_node = strtoul(argv[1], NULL, 0);
	srv.sq_port = strtoul(argv[2], NULL, 0);

	sock = socket(AF_QIPCRTR, SOCK_DGRAM, 0);
	if (sock < 0) {
		perror("socket");
		return 1;
	}
	setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

	buf[0] = 0x00;              /* request */
	buf[1] = 0x01; buf[2] = 0x00;   /* transaction id */
	buf[3] = SERVREG_NOTIF_RESTART_PD & 0xff;
	buf[4] = SERVREG_NOTIF_RESTART_PD >> 8;
	off = 7;

	/* TLV 01: the service path, a QMI string: length byte, then characters */
	buf[off++] = 0x01;
	buf[off++] = (uint8_t)((len + 1) & 0xff);
	buf[off++] = (uint8_t)((len + 1) >> 8);
	buf[off++] = (uint8_t)len;
	memcpy(buf + off, argv[3], len);
	off += len;

	buf[5] = (uint8_t)((off - 7) & 0xff);
	buf[6] = (uint8_t)((off - 7) >> 8);

	if (sendto(sock, buf, off, 0, (void *)&srv, sizeof(srv)) < 0) {
		perror("sendto");
		return 1;
	}

	n = recv(sock, resp, sizeof(resp), 0);
	if (n < 7) {
		perror("recv");
		return 1;
	}

	printf("restart %s: %zd bytes:", argv[3], n);
	for (int i = 0; i < n && i < 40; i++)
		printf(" %02x", resp[i]);
	printf("\n");

	/* find the result TLV (type 0x02): u16 result, u16 error */
	for (int i = 7; i + 4 <= n; ) {
		int type = resp[i];
		int tlen = resp[i + 1] | resp[i + 2] << 8;
		if (type == 0x02 && tlen >= 4) {
			printf("result %u error %u\n",
			       resp[i + 3] | resp[i + 4] << 8,
			       resp[i + 5] | resp[i + 6] << 8);
			break;
		}
		i += 3 + tlen;
	}
	return 0;
}
