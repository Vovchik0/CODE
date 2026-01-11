; General purpose functions and data

; Wait for keypress
wait_key:
    mov ah, 0
    int 0x16
    ret

; Get keyboard status (non-blocking)
get_key_status:
    mov ah, 1
    int 0x16
    ret

; Reboot system
reboot:
    jmp 0xffff:0000

; --- Simple "File System" (Data section) ---
; A list of "files" with names and some dummy content
file_table:
    db 'SYSTEM  TXT', 0
    dw file1_content
    db 'README  TXT', 0
    dw file2_content
    db 0 ; End of table

file1_content db 'FSOS v1.0 Kernel System File', 0
file2_content db 'Welcome to FSOS!', 0

; Global variables
mouse_x dw 160
mouse_y dw 100
mouse_buttons dw 0
last_mouse_x dw 160
last_mouse_y dw 100
