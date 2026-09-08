#ifndef C_TCP_SOCKET_SNAPSHOT_H
#define C_TCP_SOCKET_SNAPSHOT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Returns 0 on success and an errno-compatible value on failure.
// The caller owns *utf8_lines and must release it with vpg_free_tcp_snapshot.
int vpg_copy_tcp_snapshot(uint16_t local_port_filter, char **utf8_lines, size_t *length);
void vpg_free_tcp_snapshot(char *buffer);

#ifdef __cplusplus
}
#endif

#endif
