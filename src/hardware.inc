; Minimal Game Boy hardware registers.
; RGBDS does not ship hardware.inc, so this is ours. Grow it as needed.

; --- LCD / PPU ---
def rLCDC  equ $FF40
def rSTAT  equ $FF41
def rSCY   equ $FF42
def rSCX   equ $FF43
def rLY    equ $FF44
def rLYC   equ $FF45
def rDMA   equ $FF46
def rBGP   equ $FF47
def rOBP0  equ $FF48
def rOBP1  equ $FF49
def rWY    equ $FF4A
def rWX    equ $FF4B

; --- interrupts / input ---
def rIF    equ $FF0F
def rIE    equ $FFFF
def rP1    equ $FF00

; rIE/rIF bits, one per interrupt vector: VBlank $40, STAT $48, Timer $50,
; Serial $58, Joypad $60.
def IEF_VBLANK equ %00000001
def IEF_STAT   equ %00000010
def IEF_TIMER  equ %00000100
def IEF_SERIAL equ %00001000
def IEF_JOYPAD equ %00010000

; rSTAT bits. The low three are read-only mode/coincidence flags; the upper
; four select which sources raise the STAT interrupt. Bit 6 is the LYC=LY
; source, which is what the status band uses.
def STATF_LYC    equ %01000000
def STATF_MODE00 equ %00001000
def STATF_MODE01 equ %00010000
def STATF_MODE10 equ %00100000

; --- LCDC bits ---
def LCDCF_ON     equ %10000000
def LCDCF_WIN9C00 equ %01000000
def LCDCF_WINON  equ %00100000
def LCDCF_BG8000 equ %00010000   ; BG tile data at $8000 (unsigned)
def LCDCF_BG9C00 equ %00001000   ; BG map at $9C00
def LCDCF_OBJ16  equ %00000100
def LCDCF_OBJON  equ %00000010
def LCDCF_BGON   equ %00000001

; --- sound (APU) ---
; Channel 1 is the tune, channel 4 the one-shot effects -- see UpdateMusic and
; UpdateSfx in main.asm. rNR52's top bit powers the APU and gates every other
; register here, so it goes in before any of them.
def rNR10 equ $FF10              ; ch1 sweep
def rNR11 equ $FF11              ; ch1 duty/length
def rNR12 equ $FF12              ; ch1 volume/envelope
def rNR13 equ $FF13              ; ch1 period, low 8 bits
def rNR14 equ $FF14              ; ch1 period high bits + trigger
def rNR21 equ $FF16
def rNR22 equ $FF17
def rNR23 equ $FF18
def rNR24 equ $FF19
def rNR41 equ $FF20              ; ch4 length
def rNR42 equ $FF21              ; ch4 volume/envelope
def rNR43 equ $FF22              ; ch4 clock shift + divisor: the noise "pitch"
def rNR44 equ $FF23              ; ch4 trigger
def rNR50 equ $FF24              ; master volume, left in the low nibble
def rNR51 equ $FF25              ; which channels go to which output
def rNR52 equ $FF26              ; bit 7 powers the APU

def AUDENA_ON   equ %10000000
def AUDENA_OFF  equ %00000000
def AUDTRIGGER  equ %10000000
def AUDDUTY_50  equ %10000000    ; NRx1 bits 7-6: 50% duty
def AUDVOL_MAX  equ %11110000    ; NRx2: volume 15, no envelope

; --- VRAM layout ---
def _VRAM  equ $8000             ; tile data (and unsigned tile indices)
def _SCRN0 equ $9800             ; BG map 0 (32x32)
def _SCRN1 equ $9C00             ; BG map 1
def _OAMRAM equ $FE00            ; 40 sprites x 4 bytes, only writable in VBlank

; --- VRAM/OAM sizes ---
def TILE_BYTES equ 16            ; one 8x8 2bpp tile
def SCRN_BYTES equ 32 * 32

; --- joypad (rP1) ---
; Write a nibble with one of these clear to select that row, then read: the
; selected row's buttons read 0 when held.
def P14_DPAD    equ %00100000
def P15_BUTTONS equ %00010000
def PAD_RIGHT   equ %00000001
def PAD_LEFT    equ %00000010
def PAD_UP      equ %00000100
def PAD_DOWN    equ %00001000
def PAD_A       equ %00010000
def PAD_B       equ %00100000
def PAD_SELECT  equ %01000000
def PAD_START   equ %10000000

; --- palette ---
; Shade 0 is white and 3 is black. Index 0 must be black because the Spectrum
; draws coloured ink on black paper.
def PALETTE_INK_ON_BLACK equ %00011011
