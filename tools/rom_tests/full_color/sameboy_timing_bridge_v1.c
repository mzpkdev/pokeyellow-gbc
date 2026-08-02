/* Hash-bound SameBoy v1.0.3 timing bridge.
 *
 * The public core API exposes memory-write callbacks but intentionally hides
 * the cycle counter.  Building this tiny program against the pinned source
 * with GB_INTERNAL gives the callback read-only access to the core's absolute
 * 8 MHz tick counter.  It never estimates cycles from LY, DIV, host time, or
 * transfer byte counts.
 */
#define GB_INTERNAL
#include "gb.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BRIDGE_VERSION "SameBoy Timing Bridge v1.0.3"
#define EVENT_CALIBRATION_START 3
#define EVENT_CALIBRATION_END 4

typedef struct {
    uint64_t frame;
    uint64_t *input_frames;
    uint8_t *input_masks;
    size_t input_count;
    size_t input_index;
    uint32_t usable_cycles[13];
    uint64_t calibration_start[13];
    bool calibration_active[13];
    FILE *output;
    uint16_t event_address;
    uint16_t row_address;
    uint16_t sequence_address;
    uint16_t probe_address;
    uint16_t probe_cycles_address;
    unsigned observations;
} context_t;

/* SameBoy's CGB display path always converts pixels, even when this bridge
 * only consumes memory-write markers. Match the pinned tester's headless
 * initialization instead of leaving the core's encode callback and output
 * buffer null before the first VBlank. */
static uint32_t pixels[256 * 224];

static uint32_t rgb_encode(GB_gameboy_t *gb, uint8_t r, uint8_t g, uint8_t b)
{
    (void)gb;
#ifdef GB_BIG_ENDIAN
    return (r << 0) | (g << 8) | (b << 16);
#else
    return (r << 24) | (g << 16) | (b << 8);
#endif
}

static void usage(const char *name)
{
    fprintf(stderr,
            "usage: %s --rom ROM --boot-rom BOOT --input-script TSV --output TSV "
            "--event-address HEX --row-address HEX --sequence-address HEX "
            "--probe-address HEX --probe-cycles-address HEX --budgets TSV "
            "--max-cycles N\n", name);
}

static unsigned long parse_unsigned(const char *text, int base, const char *name)
{
    char *end = NULL;
    errno = 0;
    unsigned long value = strtoul(text, &end, base);
    if (errno || !end || *end) {
        fprintf(stderr, "invalid %s: %s\n", name, text);
        exit(2);
    }
    return value;
}

static bool observe_write(GB_gameboy_t *gb, uint16_t address, uint8_t value)
{
    context_t *context = GB_get_user_data(gb);
    if (address != context->event_address || value == 0) return true;
    uint8_t row = GB_read_memory(gb, context->row_address);
    if (row < 1 || row > 12) {
        fputs("ROM emitted an unknown timing row\n", stderr);
        exit(5);
    }
    if (value == EVENT_CALIBRATION_START) {
        context->calibration_start[row] = gb->absolute_debugger_ticks;
        context->calibration_active[row] = true;
    }
    else if (value == EVENT_CALIBRATION_END) {
        if (!context->calibration_active[row]) {
            fputs("ROM ended timing calibration without a start\n", stderr);
            exit(5);
        }
        uint64_t overhead = gb->absolute_debugger_ticks - context->calibration_start[row];
        if (!overhead || overhead >= context->usable_cycles[row]) {
            fputs("timing calibration leaves no safe cycle threshold\n", stderr);
            exit(5);
        }
        uint32_t probe_cycles = context->usable_cycles[row] - overhead + 1;
        GB_write_memory(gb, context->probe_cycles_address, probe_cycles & 0xFF);
        GB_write_memory(gb, context->probe_cycles_address + 1, probe_cycles >> 8);
        GB_write_memory(gb, context->probe_cycles_address + 2, probe_cycles >> 16);
        GB_write_memory(gb, context->probe_cycles_address + 3, probe_cycles >> 24);
        context->calibration_active[row] = false;
    }
    uint16_t sequence = GB_read_memory(gb, context->sequence_address);
    sequence |= (uint16_t)GB_read_memory(gb, context->sequence_address + 1) << 8;
    uint8_t probe = GB_read_memory(gb, context->probe_address);
    uint32_t probe_cycles = GB_read_memory(gb, context->probe_cycles_address);
    probe_cycles |= (uint32_t)GB_read_memory(gb, context->probe_cycles_address + 1) << 8;
    probe_cycles |= (uint32_t)GB_read_memory(gb, context->probe_cycles_address + 2) << 16;
    probe_cycles |= (uint32_t)GB_read_memory(gb, context->probe_cycles_address + 3) << 24;
    uint8_t ly = GB_read_memory(gb, 0xFF44);
    fprintf(context->output, "%u\t%u\t%u\t%" PRIu64 "\t%u\t%u\t%u\n",
            row, value, sequence, gb->absolute_debugger_ticks, ly, probe,
            probe_cycles);
    context->observations++;
    return true;
}

static void apply_input(GB_gameboy_t *gb, context_t *context)
{
    while (context->input_index < context->input_count &&
           context->input_frames[context->input_index] == context->frame) {
        GB_set_key_mask(gb, context->input_masks[context->input_index]);
        context->input_index++;
    }
}

static void vblank(GB_gameboy_t *gb, GB_vblank_type_t type)
{
    if (type != GB_VBLANK_TYPE_NORMAL_FRAME) return;
    context_t *context = GB_get_user_data(gb);
    context->frame++;
    apply_input(gb, context);
}

static void load_input_script(const char *path, context_t *context)
{
    FILE *file = fopen(path, "r");
    if (!file) { perror(path); exit(2); }
    char header[64];
    if (!fgets(header, sizeof(header), file) || strcmp(header, "frame\tkey_mask\n") != 0) {
        fputs("input script has the wrong header\n", stderr);
        exit(2);
    }
    size_t capacity = 64;
    context->input_frames = malloc(capacity * sizeof(*context->input_frames));
    context->input_masks = malloc(capacity * sizeof(*context->input_masks));
    if (!context->input_frames || !context->input_masks) { perror("malloc"); exit(2); }
    uint64_t prior = 0;
    unsigned long long frame;
    unsigned mask;
    while (fscanf(file, "%llu\t%u\n", &frame, &mask) == 2) {
        if (mask > 255 || (context->input_count && frame <= prior)) {
            fputs("input script is not strictly ordered or has an invalid mask\n", stderr);
            exit(2);
        }
        if (context->input_count == capacity) {
            capacity *= 2;
            context->input_frames = realloc(context->input_frames, capacity * sizeof(*context->input_frames));
            context->input_masks = realloc(context->input_masks, capacity * sizeof(*context->input_masks));
            if (!context->input_frames || !context->input_masks) { perror("realloc"); exit(2); }
        }
        context->input_frames[context->input_count] = frame;
        context->input_masks[context->input_count++] = mask;
        prior = frame;
    }
    if (!feof(file) || !context->input_count || context->input_frames[0] != 0) {
        fputs("input script is malformed or lacks frame zero\n", stderr);
        exit(2);
    }
    fclose(file);
}

static void load_budgets(const char *path, context_t *context)
{
    FILE *file = fopen(path, "r");
    if (!file) { perror(path); exit(2); }
    char header[64];
    if (!fgets(header, sizeof(header), file) || strcmp(header, "row\tusable_cycles\n") != 0) {
        fputs("budget table has the wrong header\n", stderr);
        exit(2);
    }
    unsigned row, budget, count = 0;
    while (fscanf(file, "%u\t%u\n", &row, &budget) == 2) {
        if (row < 1 || row > 12 || !budget || budget > 2000000000U || context->usable_cycles[row]) {
            fputs("budget table has a duplicate or invalid cycle row\n", stderr);
            exit(2);
        }
        context->usable_cycles[row] = budget;
        count++;
    }
    if (!feof(file) || count != 12) {
        fputs("budget table does not contain exactly 12 rows\n", stderr);
        exit(2);
    }
    fclose(file);
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts(BRIDGE_VERSION);
        return 0;
    }
    const char *rom = NULL, *boot = NULL, *input_script = NULL, *budgets = NULL, *output = NULL;
    context_t context = {0};
    uint64_t max_cycles = 0;
    for (int i = 1; i < argc; i++) {
        if (i + 1 >= argc) { usage(argv[0]); return 2; }
        const char *value = argv[++i];
        if (strcmp(argv[i - 1], "--rom") == 0) rom = value;
        else if (strcmp(argv[i - 1], "--boot-rom") == 0) boot = value;
        else if (strcmp(argv[i - 1], "--input-script") == 0) input_script = value;
        else if (strcmp(argv[i - 1], "--budgets") == 0) budgets = value;
        else if (strcmp(argv[i - 1], "--output") == 0) output = value;
        else if (strcmp(argv[i - 1], "--event-address") == 0)
            context.event_address = parse_unsigned(value, 16, "event address");
        else if (strcmp(argv[i - 1], "--row-address") == 0)
            context.row_address = parse_unsigned(value, 16, "row address");
        else if (strcmp(argv[i - 1], "--sequence-address") == 0)
            context.sequence_address = parse_unsigned(value, 16, "sequence address");
        else if (strcmp(argv[i - 1], "--probe-address") == 0)
            context.probe_address = parse_unsigned(value, 16, "probe address");
        else if (strcmp(argv[i - 1], "--probe-cycles-address") == 0)
            context.probe_cycles_address = parse_unsigned(value, 16, "probe cycles address");
        else if (strcmp(argv[i - 1], "--max-cycles") == 0)
            max_cycles = parse_unsigned(value, 10, "maximum cycles");
        else { usage(argv[0]); return 2; }
    }
    if (!rom || !boot || !input_script || !budgets || !output || !max_cycles ||
        !context.event_address || !context.row_address ||
        !context.sequence_address || !context.probe_address ||
        !context.probe_cycles_address) {
        usage(argv[0]);
        return 2;
    }
    context.output = fopen(output, "w");
    if (!context.output) { perror(output); return 2; }
    fprintf(context.output, "row\tevent\tsequence\tcore_cycles\tly\tprobe\tprobe_cycles\n");
    load_input_script(input_script, &context);
    load_budgets(budgets, &context);

    GB_gameboy_t gb;
    GB_init(&gb, GB_MODEL_CGB_E);
    GB_set_user_data(&gb, &context);
    GB_set_write_memory_callback(&gb, observe_write);
    GB_set_vblank_callback(&gb, vblank);
    GB_set_pixels_output(&gb, pixels);
    GB_set_rgb_encode_callback(&gb, rgb_encode);
    GB_set_emulate_joypad_bouncing(&gb, false);
    if (GB_load_boot_rom(&gb, boot) || GB_load_rom(&gb, rom)) {
        fputs("failed to load SameBoy input identity\n", stderr);
        GB_free(&gb);
        fclose(context.output);
        return 3;
    }
    apply_input(&gb, &context);
    uint64_t start = gb.absolute_debugger_ticks;
    while (gb.absolute_debugger_ticks - start < max_cycles) GB_run(&gb);
    GB_free(&gb);
    free(context.input_frames);
    free(context.input_masks);
    fclose(context.output);
    if (!context.observations) {
        fputs("checkpoint produced no timing marker writes\n", stderr);
        return 4;
    }
    return 0;
}
