#include "CTCPSocketSnapshot.h"

#include <errno.h>
#include <stdlib.h>

#if defined(__APPLE__) && defined(__MACH__)

#define PRIVATE 1
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/in_pcb.h>
#include <netinet/tcp_fsm.h>
#include <netinet/tcp_var.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/socketvar.h>
#include <sys/sysctl.h>

struct vpg_xgen_n {
    uint32_t xgn_len;
    uint32_t xgn_kind;
};

static size_t vpg_roundup64(size_t value) {
    if (value == 0) {
        return sizeof(uint64_t);
    }
    return 1 + ((value - 1) | (sizeof(uint64_t) - 1));
}

static const char *vpg_tcp_state_name(int state) {
    switch (state) {
        case TCPS_CLOSED: return "CLOSED";
        case TCPS_LISTEN: return "LISTEN";
        case TCPS_SYN_SENT: return "SYN_SENT";
        case TCPS_SYN_RECEIVED: return "SYN_RECEIVED";
        case TCPS_ESTABLISHED: return "ESTABLISHED";
        case TCPS_CLOSE_WAIT: return "CLOSE_WAIT";
        case TCPS_FIN_WAIT_1: return "FIN_WAIT_1";
        case TCPS_CLOSING: return "CLOSING";
        case TCPS_LAST_ACK: return "LAST_ACK";
        case TCPS_FIN_WAIT_2: return "FIN_WAIT_2";
        case TCPS_TIME_WAIT: return "TIME_WAIT";
        default: return "UNKNOWN";
    }
}

static int vpg_append_line(char **buffer, size_t *used, size_t *capacity, const char *line) {
    size_t line_length = strlen(line);
    size_t required = *used + line_length + 1;
    if (required > *capacity) {
        size_t new_capacity = *capacity == 0 ? 1024 : *capacity;
        while (new_capacity < required) {
            if (new_capacity > SIZE_MAX / 2) {
                return EOVERFLOW;
            }
            new_capacity *= 2;
        }
        char *resized = realloc(*buffer, new_capacity);
        if (resized == NULL) {
            return ENOMEM;
        }
        *buffer = resized;
        *capacity = new_capacity;
    }
    memcpy(*buffer + *used, line, line_length);
    *used += line_length;
    (*buffer)[(*used)++] = '\n';
    return 0;
}

static int vpg_emit_connection(
    const struct xinpcb_n *inp,
    const struct xtcpcb_n *tp,
    uint16_t local_port_filter,
    char **output,
    size_t *used,
    size_t *capacity
) {
    uint16_t local_port = ntohs(inp->inp_lport);
    if (local_port_filter != 0 && local_port != local_port_filter) {
        return 0;
    }

    char local_address[INET6_ADDRSTRLEN] = {0};
    char remote_address[INET6_ADDRSTRLEN] = {0};
    int family = AF_UNSPEC;
    const void *local_pointer = NULL;
    const void *remote_pointer = NULL;

    if ((inp->inp_vflag & INP_IPV4) != 0) {
        family = AF_INET;
        local_pointer = &inp->inp_laddr;
        remote_pointer = &inp->inp_faddr;
    } else if ((inp->inp_vflag & INP_IPV6) != 0) {
        family = AF_INET6;
        local_pointer = &inp->in6p_laddr;
        remote_pointer = &inp->in6p_faddr;
    } else {
        return 0;
    }

    if (inet_ntop(family, local_pointer, local_address, sizeof(local_address)) == NULL ||
        inet_ntop(family, remote_pointer, remote_address, sizeof(remote_address)) == NULL) {
        return errno == 0 ? EINVAL : errno;
    }

    char line[256];
    int written = snprintf(
        line,
        sizeof(line),
        "%s|%s|%u|%s|%u",
        vpg_tcp_state_name(tp->t_state),
        local_address,
        (unsigned)local_port,
        remote_address,
        (unsigned)ntohs(inp->inp_fport)
    );
    if (written < 0 || (size_t)written >= sizeof(line)) {
        return EOVERFLOW;
    }
    return vpg_append_line(output, used, capacity, line);
}

int vpg_copy_tcp_snapshot(uint16_t local_port_filter, char **utf8_lines, size_t *length) {
    if (utf8_lines == NULL || length == NULL) {
        return EINVAL;
    }
    *utf8_lines = NULL;
    *length = 0;

    size_t buffer_length = 0;
    if (sysctlbyname("net.inet.tcp.pcblist_n", NULL, &buffer_length, NULL, 0) != 0) {
        return errno;
    }
    if (buffer_length <= sizeof(struct xinpgen)) {
        char *empty = calloc(1, 1);
        if (empty == NULL) {
            return ENOMEM;
        }
        *utf8_lines = empty;
        return 0;
    }

    char *pcb_buffer = malloc(buffer_length);
    if (pcb_buffer == NULL) {
        return ENOMEM;
    }
    if (sysctlbyname("net.inet.tcp.pcblist_n", pcb_buffer, &buffer_length, NULL, 0) != 0) {
        int saved_errno = errno;
        free(pcb_buffer);
        return saved_errno;
    }

    const struct xinpgen *header = (const struct xinpgen *)pcb_buffer;
    if (header->xig_len < sizeof(struct xinpgen) || header->xig_len > buffer_length) {
        free(pcb_buffer);
        return EPROTO;
    }

    size_t offset = vpg_roundup64(header->xig_len);
    if (offset > buffer_length) {
        free(pcb_buffer);
        return EPROTO;
    }

    const struct xinpcb_n *inp = NULL;
    const struct xtcpcb_n *tp = NULL;
    char *output = NULL;
    size_t used = 0;
    size_t capacity = 0;
    int result = 0;

    while (offset + sizeof(struct vpg_xgen_n) <= buffer_length) {
        const struct vpg_xgen_n *record = (const struct vpg_xgen_n *)(pcb_buffer + offset);
        if (record->xgn_len <= sizeof(struct xinpgen)) {
            break;
        }
        size_t rounded_length = vpg_roundup64(record->xgn_len);
        if (record->xgn_len < sizeof(struct vpg_xgen_n) ||
            rounded_length < record->xgn_len ||
            offset > buffer_length - rounded_length) {
            result = EPROTO;
            break;
        }

        switch (record->xgn_kind) {
            case XSO_INPCB:
                if (record->xgn_len < sizeof(struct xinpcb_n)) {
                    result = EPROTO;
                } else {
                    inp = (const struct xinpcb_n *)record;
                }
                break;
            case XSO_TCPCB:
                if (record->xgn_len < sizeof(struct xtcpcb_n)) {
                    result = EPROTO;
                } else {
                    tp = (const struct xtcpcb_n *)record;
                }
                break;
            default:
                break;
        }
        if (result != 0) {
            break;
        }

        if (inp != NULL && tp != NULL) {
            result = vpg_emit_connection(inp, tp, local_port_filter, &output, &used, &capacity);
            inp = NULL;
            tp = NULL;
            if (result != 0) {
                break;
            }
        }
        offset += rounded_length;
    }

    free(pcb_buffer);
    if (result != 0) {
        free(output);
        return result;
    }
    if (output == NULL) {
        output = calloc(1, 1);
        if (output == NULL) {
            return ENOMEM;
        }
    }
    *utf8_lines = output;
    *length = used;
    return 0;
}

#else

int vpg_copy_tcp_snapshot(uint16_t local_port_filter, char **utf8_lines, size_t *length) {
    (void)local_port_filter;
    if (utf8_lines != NULL) {
        *utf8_lines = NULL;
    }
    if (length != NULL) {
        *length = 0;
    }
    return ENOTSUP;
}

#endif

void vpg_free_tcp_snapshot(char *buffer) {
    free(buffer);
}
