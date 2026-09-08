#include "IntelBrightnessBridge.h"

#if defined(__APPLE__) && defined(__MACH__)
#include <ApplicationServices/ApplicationServices.h>
#include <IOKit/graphics/IOGraphicsLib.h>
#include <IOKit/IOKitLib.h>

static io_service_t vpg_display_service(CGDirectDisplayID display_id) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    io_service_t service = CGDisplayIOServicePort(display_id);
#pragma clang diagnostic pop
    return service;
}

int32_t vpg_iokit_get_brightness(uint32_t display_id, float *brightness) {
    if (brightness == NULL) {
        return kIOReturnBadArgument;
    }
    io_service_t service = vpg_display_service((CGDirectDisplayID)display_id);
    if (service == IO_OBJECT_NULL) {
        return kIOReturnNotFound;
    }
    return IODisplayGetFloatParameter(
        service,
        kNilOptions,
        CFSTR(kIODisplayBrightnessKey),
        brightness
    );
}

int32_t vpg_iokit_set_brightness(uint32_t display_id, float brightness) {
    if (!(brightness >= 0.0f && brightness <= 1.0f)) {
        return kIOReturnBadArgument;
    }
    io_service_t service = vpg_display_service((CGDirectDisplayID)display_id);
    if (service == IO_OBJECT_NULL) {
        return kIOReturnNotFound;
    }
    return IODisplaySetFloatParameter(
        service,
        kNilOptions,
        CFSTR(kIODisplayBrightnessKey),
        brightness
    );
}
#else
#include <errno.h>
int32_t vpg_iokit_get_brightness(uint32_t display_id, float *brightness) {
    (void)display_id;
    (void)brightness;
    return ENOTSUP;
}
int32_t vpg_iokit_set_brightness(uint32_t display_id, float brightness) {
    (void)display_id;
    (void)brightness;
    return ENOTSUP;
}
#endif
