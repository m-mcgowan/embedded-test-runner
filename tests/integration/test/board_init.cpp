/// Board init for integration tests.
#include <Arduino.h>

bool board_init(Print& log) {
    log.println("[etst] board_init OK");
    return true;
}
