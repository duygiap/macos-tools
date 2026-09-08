#ifndef INTEL_BRIGHTNESS_BRIDGE_H
#define INTEL_BRIGHTNESS_BRIDGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int32_t vpg_iokit_get_brightness(uint32_t display_id, float *brightness);
int32_t vpg_iokit_set_brightness(uint32_t display_id, float brightness);

#ifdef __cplusplus
}
#endif

#endif
