// Probe the servreg notification service (QMI service 0x42) with the message
// ids it may use for registering a listener, and print what comes back.
//
// The kernel registers a listener for msm/modem/wlan_pd and gets no answer
// here; this sends the same shape of message by hand so the modem's own reply
// can be seen, byte for byte.
//
// Usage: servreg-probe <node> <port> <pd name>
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

static int send_probe(int sock, struct sockaddr_qrtr *srv, int id,
		      const char *name, int enable)
{
	uint8_t buf[512], resp[512];
	size_t len = strlen(name);
	ssize_t n;
	int tlvs = 0;
	int off = 7;

	/* QMI request header: flags, transaction id, message id, length */
	buf[0] = 0;
	buf[1] = 0x01; buf[2] = 0x00;
	buf[3] = (uint8_t)id; buf[4] = (uint8_t)(id >> 8);
	/* TLV 01: name, a QMI string: one length byte, then the characters */
	buf[off++] = 0x01;
	buf[off++] = (uint8_t)((len + 1) & 0xff); buf[off++] = (uint8_t)((len + 1) >> 8);
	buf[off++] = (uint8_t)len;
	memcpy(buf + off, name, len); off += len;
	tlvs = 4 + len;
	/* TLV 02: enable (u8) */
	buf[off++] = 0x02;
	buf[off++] = 1; buf[off++] = 0;
	buf[off++] = enable ? 1 : 0;
	tlvs += 4;

	buf[5] = (uint8_t)(tlvs & 0xff); buf[6] = (uint8_t)(tlvs >> 8);

	if (sendto(sock, buf, off, 0, (void *)srv, sizeof(*srv)) < 0)
		return -1;

	n = recv(sock, resp, sizeof(resp), 0);
	if (n < 7)
		return -1;

	printf("  id 0x%04x -> %zd bytes: result %u error %u",
	       id, n, resp[7] | resp[8] << 8, resp[9] | resp[10] << 8);
	for (int i = 7; i < n && i < 40; i++)
		printf(" %02x", resp[i]);
	printf("\n");
	fflush(stdout);
	return 0;
}

int main(int argc, char **argv)
{
	struct sockaddr_qrtr srv = { .sq_family = AF_QIPCRTR };
	struct timeval tv = { .tv_sec = 2 };
	int sock, id;

	if (argc != 4) {
		fprintf(stderr, "usage: %s <node> <port> <pd name>\n", argv[0]);
		return 1;
	}
	srv.sq_node = strtoul(argv[1], NULL, 0);
	srv.sq_port = strtoul(argv[2], NULL, 0);

	sock = socket(AF_QIPCRTR, SOCK_DGRAM, 0);
	if (sock < 0) {
		perror("socket");
		return 1;
	}
	setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

	printf("probing service %s at node %u port %u\n", argv[3],
	       srv.sq_node, srv.sq_port);
	for (id = 0x20; id <= 0x2f; id++)
		send_probe(sock, &srv, id, argv[3], 1);

	return 0;
}

