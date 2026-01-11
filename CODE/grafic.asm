; Graphics functions for Mode 13h (320x200)

; Fill screen with color in AL
clear_screen:
    push es
    push cx
    push di
    push ax
    mov bx, 0xa000
    mov es, bx
    xor di, di
    mov cx, 32000 ; 64000 bytes / 2 (we use stosw)
    mov ah, al
    rep stosw
    pop ax
    pop di
    pop cx
    pop es
    ret

; Draw a rectangle
; AL = color, CX = x, DX = y, SI = width, DI = height
draw_rect:
    pusha
    push es
    mov bx, 0xa000
    mov es, bx
    
.row_loop:
    push cx
    push si
    
    ; offset = y * 320 + x
    mov ax, dx
    mov bx, 320
    mul bx
    add ax, cx
    mov bx, ax ; bx = offset
    
.col_loop:
    mov [es:bx], al
    inc bx
    dec si
    jnz .col_loop
    
    pop si
    pop cx
    inc dx
    dec di
    jnz .row_loop
    
    pop es
    popa
    ret

; Draw a character (using BIOS font)
; AL = char, CX = x, DX = y
draw_char:
    pusha
    push ds
    
    mov ax, 0xF000
    mov ds, ax
    mov si, 0xFA6E ; Start of 8x8 font
    
    xor ah, ah
    shl ax, 3 ; char * 8
    add si, ax ; DS:SI points to char bitmap
    
    mov bl, 8 ; 8 rows
.row_loop:
    lodsb ; AL = bitmap row
    mov bh, 8 ; 8 pixels
    push cx
.pixel_loop:
    test al, 0x80
    jz .skip_pixel
    
    ; Draw white pixel (color 15)
    push ax
    mov al, 0 ; Black text
    ; Check if we need white or black
    ; For now, let's use black as requested for MS-DOS Executive
    ; Actually, let's use the color in BL but BL is used.
    ; Let's use color 0 (black) hardcoded for now for speed.
    
    push es
    push di
    mov di, 0xa000
    mov es, di
    push dx
    push ax
    mov ax, 320
    mul dx
    add ax, cx
    mov di, ax
    pop ax
    mov al, 0 ; Black
    mov [es:di], al
    pop dx
    pop di
    pop es
    pop ax
    
.skip_pixel:
    shl al, 1
    inc cx
    dec bh
    jnz .pixel_loop
    pop cx
    inc dx
    dec bl
    jnz .row_loop
    
    pop ds
    popa
    ret

; Draw a string
; SI = offset to string, CX = x, DX = y
draw_text:
    pusha
.loop:
    lodsb
    or al, al
    jz .done
    call draw_char
    add cx, 8
    jmp .loop
.done:
    popa
    ret
