from math import ceil, floor
from colorama import Fore, Back, Style

def printi(msg, *args):
    print(Fore.MAGENTA + msg + Style.RESET_ALL, *args)
def printe(msg, *args):
    print(Fore.YELLOW + msg + Style.RESET_ALL, *args)
def printd(msg, *args):
    print(Fore.BLUE + msg + Style.RESET_ALL, *args)

def _round_down_word(val):
    return (val // 4) * 4

def _round_up_word(val):
    return ceil(val  / 4) * 4

def _round_down_page(val):
    return (val // 4096) * 4096

def _round_up_page(val):
    return ceil(val  / 4096) * 4096

def _seconds_to_frames(seconds):
    return int(round(60 * seconds))

def _check_int_size(args, int_pos):
    size = 0x20000
    if args.extended:
        size += 0x20000

    if int_pos > size:
        raise IndexError(f"Internal firmware pos {int_pos} exceeded internal firmware size {size}.")

def add_patch_args(parser):

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--disable-sleep", action="store_true",
                        help="Disables sleep timer")
    group.add_argument("--sleep-time", type=float, default=None,
                        help="Go to sleep after this many seconds of inactivity.. "
                         "Valid range: [1, 1092]"
                        )

    parser.add_argument("--hard-reset-time", type=float, default=None,
                         help="Hold power button for this many seconds to perform hard reset."
                         )
    parser.add_argument("--mario-song-time", type=float, default=None,
                         help="Hold the A button for this many seconds on the time "
                         "screen to launch the mario drawing song easter egg."
                         )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--slim", action="store_true", default=False,
                        help="Remove mario song and sleeping images from extflash. Perform other space-saving measures.")
    group.add_argument("--clock-only", action="store_true", default=False,
                        help="Everything in --slim plus remove SMB2. TODO: remove Ball.")


def validate_patch_args(parser, args):
    if args.sleep_time and (args.sleep_time < 1 or args.sleep_time > 1092):
        parser.error("--sleep-time must be in range [1, 1092]")
    if args.mario_song_time and (args.mario_song_time < 1 or args.mario_song_time > 1092):
        parser.error("--mario_song-time must be in range [1, 1092]")

    if args.clock_only:
        args.slim = True


def _relocate_external_functions(device, offset):
    """
    data start: 0x900bfd1c
    fn start: 0x900c0258
    fn end:   0x900c34c0
    fn len: 12904
    """

    references = [
        0x00d330,
        0x00d310,
        0x00d308,
        0x00d338,
        0x00d348,
        0x00d360,
        0x00d368,
        0x00d388,
        0x00d358,
        0x00d320,
        0x00d350,
        0x00d380,
        0x00d378,
        0x00d318,
        0x00d390,
        0x00d370,
        0x00d340,
        0x00d398,
        0x00d328,
    ]
    for reference in references:
        device.internal.add(reference, offset)

    references = [
        0xc1174,
        0xc313c,
        0xc049c,
        0xc1178,
        0xc220c,
        0xc3490,
        0xc3498,
    ]
    for reference in references:
        device.external.add(reference, offset)

    device.external.move(0xbfd1c, offset, size=14244)

def _print_rwdata_ext_references(rwdata):
    """
    For debugging/development purposes.
    """
    ls = {}
    for i in range(0, len(rwdata), 4):
        val = int.from_bytes(rwdata[i:i+4], 'little')
        if 0x9000_0000 <= val <= 0x9010_0000:
            ls[val] = i
    for k, val in sorted(ls.items()):
        print(f"0x{k:08X}: 0x{val:06X}")



def apply_patches(args, device):
    int_addr_start = device.internal.FLASH_BASE
    int_pos_start = 0x1_D000  # TODO: this might change if more custom code is added
    int_pos = int_pos_start

    def rwdata_add(lower, size, offset):
        lower += 0x9000_0000
        upper = lower + size

        for i in range(0, len(device.internal.rwdata), 4):
            val = int.from_bytes(device.internal.rwdata[i:i+4], 'little')
            if lower <= val < upper:
                new_val = val + offset
                print(f"    updating rwdata 0x{val:08X} -> 0x{new_val:08X}")
                device.internal.rwdata[i:i+4] = new_val.to_bytes(4, "little")

    def rwdata_erase(lower, size):
        lower += 0x9000_0000
        upper = lower + size

        for i in range(0, len(device.internal.rwdata), 4):
            val = int.from_bytes(device.internal.rwdata[i:i+4], 'little')
            if lower <= val < upper:
                device.internal.rwdata[i:i+4] = b"\x00\x00\x00\x00"

    printi("Invoke custom bootloader prior to calling stock Reset_Handler.")
    device.internal.replace(0x4, "bootloader")

    printi("Intercept button presses for macros.")
    device.internal.bl(0x6b52, "read_buttons")

    printi("Mute clock audio on first boot.")
    device.internal.asm(0x49e0, "mov.w r1, #0x00000")

    if args.debug:
        # Override fault handlers for easier debugging via gdb.
        printi("Overriding handlers for debugging.")
        device.internal.replace(0x8, "NMI_Handler")
        device.internal.replace(0xC, "HardFault_Handler")

    if args.hard_reset_time:
        hard_reset_time_ms = int(round(args.hard_reset_time * 1000))
        printi(f"Hold power button for {hard_reset_time_ms} milliseconds to perform hard reset.")
        device.internal.asm(0x9cee, f"movw r1, #{hard_reset_time_ms}")

    if args.sleep_time:
        printi(f"Setting sleep time to {args.sleep_time} seconds.")
        sleep_time_frames = _seconds_to_frames(args.sleep_time)
        device.internal.asm(0x6c3c, f"movw r2, #{sleep_time_frames}")

    if args.disable_sleep:
        printi(f"Disable sleep timer")
        device.internal.replace(0x6C40, 0x91, size=1)

    if args.mario_song_time:
        printi(f"Setting Mario Song time to {args.mario_song_time} seconds.")
        mario_song_frames = _seconds_to_frames(args.mario_song_time)
        device.internal.asm(0x6fc4, f"cmp.w r0, #{mario_song_frames}")

    if args.slim:
        # This is a lazy brute force way of updating some references
        # TODO: refactor
        palette_lookup = {}

        if args.extended:
            printd("Compressing and moving stuff stuff to internal firmware.")
            compressed_len = device.external.compress(0x0, 7772)
            device.internal.bl(0x665c, "memcpy_inflate")
            device.move_to_int(0x0, int_pos, size=compressed_len)
            device.internal.replace(0x7204, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(compressed_len)

            # SMB1 looks hard to compress since there's so many references.
            printd("Moving SMB1 ROM to internal firmware.")
            device.move_to_int(0x1e60, int_pos, size=40960)
            device.internal.replace(0x7368, int_addr_start + int_pos, size=4)
            device.internal.replace(0x10954, int_addr_start + int_pos, size=4)
            device.internal.replace(0x7218, int_addr_start + int_pos + 36864, size=4)
            int_pos += _round_up_word(40960)

            # I think these are all scenes for the clock, but not 100% sure.
            # The giant lookup table references all these, we could maybe compress
            # each individual scene.
            for i in range(0, 11620, 4):
                palette_lookup[0x9000_be60 + i] = int_addr_start + int_pos + i
            device.move_to_int(0xbe60, int_pos, size=11620)
            int_pos += _round_up_word(11620)

            # Up to here is fine
            #import ipdb; ipdb.set_trace()

            # Starting here I believe are BALL references
            device.move_to_int(0xebc4, int_pos, size=528)
            device.internal.replace(0x4154, int_addr_start + int_pos, size=4)
            rwdata_add(0xebc4, 528, (int_addr_start + int_pos) - 0x9000_ebc4)
            int_pos += _round_up_word(528)

        if False:
            patches.append("move_to_int", 0x9000_edd4, int_pos, size=100)
            patches.append("replace", 0x4570, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(100)

            references = {
                0x9000_ee38: 0x4514,
                0x9000_ee78: 0x4518,
                0x9000_eeb8: 0x4520,
                0x9000_eef8: 0x4524,
            }
            for external, internal in references.items():
                patches.append("move_to_int", external, int_pos, size=64)
                patches.append("replace", internal, int_addr_start + int_pos, size=4)
                int_pos += _round_up_word(64)


            references = [
                0x2ac,
                0x2b0,
                0x2b4,
                0x2b8,
                0x2bc,
                0x2c0,
                0x2c4,
                0x2c8,
                0x2cc,
                0x2d0,
            ]
            patches.append("move_to_int", 0x9000_ef38, int_pos, size=128*10)
            for reference in references:
                patches.append("replace", reference, int_addr_start + int_pos, size=4)
                int_pos += _round_up_word(128)

            patches.append("move_to_int", 0x9000_f438, int_pos, size=96)
            patches.append("replace", 0x456c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(96)

            patches.append("move_to_int", 0x9000_f498, int_pos, size=180)
            patches.append("replace", 0x43f8, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(180)

            # This is the first thing passed into the drawing engine.
            patches.append("move_to_int", 0x9000_f54c, int_pos, size=1100)
            patches.append("replace", 0x43fc, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(1100)

            patches.append("move_to_int", 0x9000_f998, int_pos, size=180)
            patches.append("replace", 0x4400, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(180)

            patches.append("move_to_int", 0x9000_fa4c, int_pos, size=1136)
            patches.append("replace", 0x4404, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(1136)

            patches.append("move_to_int", 0x9000_febc, int_pos, size=864)
            patches.append("replace", 0x450c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(864)

            patches.append("move_to_int", 0x9001_021c, int_pos, size=384)
            patches.append("replace", 0x4510, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_039c, int_pos, size=384)
            patches.append("replace", 0x451c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_051c, int_pos, size=384)
            patches.append("replace", 0x4410, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_069c, int_pos, size=384)
            patches.append("replace", 0x44f8, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_081c, int_pos, size=384)
            patches.append("replace", 0x4500, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_099c, int_pos, size=384)
            patches.append("replace", 0x4414, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_0b1c, int_pos, size=384)
            patches.append("replace", 0x44fc, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_0c9c, int_pos, size=384)
            patches.append("replace", 0x4504, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_0e1c, int_pos, size=384)
            patches.append("replace", 0x440c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_0f9c, int_pos, size=384)
            patches.append("replace", 0x4408, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(384)

            patches.append("move_to_int", 0x9001_111c, int_pos, size=192)
            patches.append("replace", 0x44f4, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(192)

            patches.append("move_to_int", 0x9001_11dc, int_pos, size=192)
            patches.append("replace", 0x4508, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(192)

            patches.append("move_to_int", 0x9001_129c, int_pos, size=304)
            patches.append("replace", 0x458c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(304)

            patches.append("move_to_int", 0x9001_13cc, int_pos, size=768)
            patches.append("replace", 0x4584, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(768)

            patches.append("move_to_int", 0x9001_16cc, int_pos, size=1144)
            patches.append("replace", 0x4588, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(1144)

            patches.append("move_to_int", 0x9001_1b44, int_pos, size=768)
            patches.append("replace", 0x4534, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(768)

            patches.append("move_to_int", 0x9001_1e44, int_pos, size=32)
            patches.append("replace", 0x455c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(32)

            patches.append("move_to_int", 0x9001_1e64, int_pos, size=32)
            patches.append("replace", 0x4588, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(32)

            patches.append("move_to_int", 0x9001_1e84, int_pos, size=32)
            patches.append("replace", 0x4554, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(32)

            patches.append("move_to_int", 0x9001_1ea4, int_pos, size=32)
            patches.append("replace", 0x4560, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(32)

            patches.append("move_to_int", 0x9001_1ec4, int_pos, size=32)
            patches.append("replace", 0x4564, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(32)

            patches.append("move_to_int", 0x9001_1ee4, int_pos, size=64)
            patches.append("replace", 0x453c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_1f24, int_pos, size=64)
            patches.append("replace", 0x4530, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_1f64, int_pos, size=64)
            patches.append("replace", 0x4540, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_1fa4, int_pos, size=64)
            patches.append("replace", 0x4544, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_1fe4, int_pos, size=64)
            patches.append("replace", 0x4548, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_2024, int_pos, size=64)
            patches.append("replace", 0x454c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_2064, int_pos, size=64)
            patches.append("replace", 0x452c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_20a4, int_pos, size=64)
            patches.append("replace", 0x4550, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(64)

            patches.append("move_to_int", 0x9001_20e4, int_pos, size=2016)
            patches.append("replace", 0x4574, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(2016)

            patches.append("move_to_int", 0x9001_28c4, int_pos, size=192)
            patches.append("replace", 0x4578, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(192)

            patches.append("move_to_int", 0x9001_2984, int_pos, size=640)
            patches.append("replace", 0x457c, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(640)

            patches.append("move_to_int", 0x9001_2c04, int_pos, size=320)
            patches.append("replace", 0x4538, int_addr_start + int_pos, size=4)
            int_pos += _round_up_word(320)

            # TODO: fix this
            #offset = -(int_pos - int_pos_start)
            #offset = -_round_down_page(int_pos - int_pos_start)
            #offset = -67000
            offset = -68000  # Some palette is messed up
            #offset = -68800
            #offset = -69000
            #offset = -69600 # Doesn't work
            #import ipdb; ipdb.set_trace()
            #offset = -4096 * 17 # doesn't work
        else:
            offset = 0

        mario_song_len = 0x85e40  # 548,416 bytes
        # This isn't really necessary, but we keep it here because its more explicit.
        printe("Erasing Mario Song")
        device.external.replace(0x1_2D44, b"\x00" * mario_song_len)
        rwdata_erase(0x1_2D44, mario_song_len)
        # Note, bytes starting at 0x90012ca4 leading up to the mario song
        # are also empty. TODO: maybe shift by that much as well.
        offset -= mario_song_len

        # Each tile is 16x16 pixels, stored as 256 bytes in row-major form.
        # These index into a palette. TODO: where is the palette
        # Moving this to internal firmware for now as a PoC.
        printe("Compressing clock graphics")
        compressed_len = device.external.compress(0x9_8b84, 0x1_0000)
        device.internal.bl(0x678e, "memcpy_inflate")

        printe("Moving clock graphics to internal firmware")
        device.move_to_int(0x9_8b84, int_pos, size=compressed_len)
        device.internal.replace(0x7350, int_addr_start + int_pos, size=4)
        compressed_len = _round_up_word(compressed_len)
        int_pos += compressed_len
        offset -= 0x1_0000


        # Note: the clock uses a different palette; this palette only applies
        # to ingame Super Mario Bros 1 & 2
        printe("Moving NES emulator palette.")
        device.external.move(0xa_8b84, offset, size=192)
        device.internal.add(0xb720, offset)

        # Note: UNKNOWN* represents a block of data that i haven't decoded
        # yet. If you know what the block of data is, please let me know!
        device.external.move(0xa_8c44, offset, size=8352)
        device.internal.add(0xbc44, offset)

        printe("Moving GAME menu icons 1.")
        device.external.move(0xa_ace4, offset, size=9088)
        device.internal.add(0xcea8, offset)

        printe("Moving GAME menu icons 2.")
        device.external.move(0xa_d064, offset, size=7040)
        device.internal.add(0xd2f8, offset)

        printe("Moving menu stuff (icons? meta?)")
        device.external.move(0xa_ebe4, offset, size=116)
        references = [
            0x0_d010,
            0x0_d004,
            0x0_d2d8,
            0x0_d2dc,
            0x0_d2f4,
            0x0_d2f0,
        ]
        for i, reference in enumerate(references):
            device.internal.add(reference, offset)


        if args.clock_only:
            printe("Erasing SMB2 ROM")
            device.external.replace(0xa_ec58, b"\x00" * 65536,)
            offset -= 65536
        else:
            printe("Compressing and moving SMB2 ROM.")
            compressed_len = device.external.compress(0xa_ec58, 0x1_0000)
            device.internal.bl(0x6a12, "memcpy_inflate")
            device.external.move(0xa_ec58, offset, size=compressed_len)
            device.internal.add(0x7374, offset)
            compressed_len = _round_up_word(compressed_len)
            offset -= (65536 - compressed_len)  # Move by the space savings.

            # Round to nearest page so that the length can be used as an imm
            compressed_len = _round_up_page(compressed_len)

            # Update the length of the compressed data (doesn't matter if its too large)
            device.internal.asm(0x6a0a, f"mov.w r2, #{compressed_len}")
            device.internal.asm(0x6a1e, f"mov.w r3, #{compressed_len}")

        # Not sure what this data is
        device.external.move(0xbec58, offset, size=8 * 2)
        device.internal.add(0x1_0964, offset)

        printe("Moving Palettes")
        # There are 80 colors, each in BGRA format, where A is always 0
        device.external.move(0xbec68, offset, size=320)  # Day palette [0600, 1700]
        device.external.move(0xbeda8, offset, size=320)  # Night palette [1800, 0400)
        device.external.move(0xbeee8, offset, size=320)  # Underwater palette (between 1200 and 2400 at XX:30)
        device.external.move(0xbf028, offset, size=320)  # Unknown palette. Maybe bowser castle? need to check...
        device.external.move(0xbf168, offset, size=320)  # Dawn palette [0500, 0600)

        # These are 2x uint32_t scene headers. They are MOSTLY [0x36, 0xF],
        # but there are a few like [0x30, 0xF] and [0x20, 0xF],
        device.external.move(0xbf2a8, offset, size=45 * 8)


        # IDK what this is.
        device.external.move(0xbf410, offset, size=144)
        device.internal.add(0x1658c, offset)

        # SCENE TABLE
        # Goes in chunks of 20 bytes (5 addresses)
        # Each scene is represented by 5 pointers:
        #    1. Pointer to a 2x uint32_t header (I think it's total tile (w, h) )
        #            The H is always 15, which would be 240 pixels tall.
        #            The W is usually 54, which would be 864 pixels (probably the flag pole?)
        #    2. RLE something. Usually 32 bytes.
        #    3. RLE something
        #    4. RLE something
        #    5. Palette
        #
        # The RLE encoded data could be background tilemap, animation routine, etc.
        lookup_table_start = 0xb_f4a0
        lookup_table_end   = 0xb_f838
        lookup_table_len   = lookup_table_end - lookup_table_start  # 46 * 5 * 4 = 920
        def cond_post_mario_song(addr):
            # Return True if it's beyond the mario song addr
            return 0x9001_2D44 <= addr
        for addr in range(lookup_table_start, lookup_table_end, 4):
            if device.external.int(addr) > 0x9001_2D44:
                # Past Mario Song
                device.external.add(addr, offset)
            elif args.extended and device.external.int(addr) in palette_lookup:
                device.external.replace(addr, palette_lookup[device.external.int(addr)], size=4)

        # Now move the table
        device.external.move(lookup_table_start, offset, size=lookup_table_len)
        device.internal.add(0xdf88, offset)

        device.external.move(0xbf838, offset, size=280)
        device.internal.add(0xe8f8, offset)
        device.internal.add(0xf4ec, offset)
        device.internal.add(0xf4f8, offset)
        device.internal.add(0x10098, offset)
        device.internal.add(0x105b0, offset)


        device.external.move(0xbf950, offset, size=180)
        device.internal.add(0xe2e4, offset)
        device.internal.add(0xf4fc, offset)


        device.external.move(0xbfa04, offset, size=8)
        device.internal.add(0x1_6590, offset)

        device.external.move(0xbfa0c, offset, size=784,)
        device.internal.add(0x1_0f9c, offset)


        _relocate_external_functions(device, offset)


        # BALL sounds
        device.external.move(0xc34c0, offset, size=6168)
        device.internal.add(0x43ec, offset)
        rwdata_add(0xc34c0, 6168, offset)

        device.external.move(0xc4cd8, offset, size=2984)
        device.internal.add(0x459c, offset)

        device.external.move(0xc5880, offset, size=120)
        device.internal.add(0x4594, offset)

        # Images Notes:
        #    * In-between images are just zeros.
        #
        # start: 0x900C_58F8   end: 0x900C_D83F    mario sleeping
        # start: 0x900C_D858   end: 0x900D_6C65    mario juggling
        # start: 0x900D_6C78   end: 0x900E_16E2    bowser sleeping
        # start: 0x900E_16F8   end: 0x900E_C301    mario and luigi eating pizza
        # start: 0x900E_C318   end: 0x900F_4D04    minions sleeping
        #          zero_padded_end: 0x900f_4d18
        # Total Image Length: 193_568 bytes
        printe("Deleting sleeping images.")
        total_image_length = 193_568
        device.external.replace(0xc58f8, b"\x00" * total_image_length)
        device.internal.replace(0x1097c, b"\x00"*4*5)  # Erase image references
        offset -= total_image_length


        device.external.move(0xf4d18, offset, size=2880)
        device.internal.add(0x10960, offset)


        # What is this data?
        # The memcpy to this address is all zero, so i guess its not used?
        #patches.append("move", 0x900f5858, offset, size=34728)
        #patches.append("add", 0x7210, offset, size=4)
        device.external.replace(0xf5858, b"\x00" * 34728)
        offset -= 34728

        # The last 2 4096 byte blocks represent something in settings.
        # Each only contains 0x50 bytes of data.
        # This rounds the negative offset towards zero.
        offset = _round_up_page(offset)

        printi("Update NVRAM read addresses")
        device.internal.asm(0x4856,
                 "ite ne; "
                f"movne.w r4, #{hex(0xff000 + offset)}; "
                f"moveq.w r4, #{hex(0xfe000 + offset)}",
        )
        printi("Update NVRAM write addresses")
        device.internal.asm(0x48c0,
                 "ite ne; "
                f"movne.w r4, #{hex(0xff000 + offset)}; "
                f"moveq.w r4, #{hex(0xfe000 + offset)}",
        )

        if True:
            # Disable nvram loading
            # Disable nvram saving
            #patches.append("ks_thumb", 0x48ba, "bx lr", size=2)
            pass

        # Finally, shorten the firmware
        printi("Updating end of OTFDEC pointer")
        device.internal.add(0x1_06ec, offset)
        device.external.shorten(offset)
