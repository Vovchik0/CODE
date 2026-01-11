; Finalized Windows 1.0 style Kernel for 320x200 Mode 13h

main_loop:
    ; --- Setup Segments ---
    mov ax, 0x07e0
    mov ds, ax
    mov es, ax

    ; --- Draw Background ---
    mov al, 3 ; Cyan
    call clear_screen

    ; --- Draw MS-DOS Executive Window ---
    mov al, 15 ; White background
    mov cx, 10
    mov dx, 10
    mov si, 300
    mov di, 170
    call draw_rect

    ; Window Border (Blue)
    mov al, 1
    mov cx, 10
    mov dx, 10
    mov si, 300
    mov di, 1
    call draw_rect ; Top
    mov dx, 180
    call draw_rect ; Bottom
    
    ; Title Bar
    mov al, 1 ; Blue
    mov cx, 11
    mov dx, 11
    mov si, 298
    mov di, 15
    call draw_rect

    ; Title Text
    mov si, title_text
    mov cx, 100
    mov dx, 15
    call draw_text_white

    ; Menu
    mov si, menu_text
    mov cx, 15
    mov dx, 28
    call draw_text_black

    ; Init Mouse
    mov ax, 0
    int 0x33
    mov ax, 1
    int 0x33

.gui_loop:
    jmp .gui_loop

; --- Drawing Functions ---

clear_screen:
    push es
    mov ax, 0xa000
    mov es, ax
    xor di, di
    mov cx, 32000
    mov ah, al
    rep stosw
    pop es
    ret

draw_rect:
    pusha
    push es
    mov ax, 0xa000
    mov es, ax
.row:
    push si
    push cx
    mov ax, dx
    mov bx, 320
    mul bx
    add ax, cx
    mov di, ax
.col:
    mov [es:di], al
    inc di
    dec si
    jnz .col
    pop cx
    pop si
    inc dx
    dec di
    jnz .row
    pop es
    popa
    ret

draw_text_white:
    mov bl, 15 ; White
    jmp draw_text_main

draw_text_black:
    mov bl, 0 ; Black
    jmp draw_text_main

draw_text_main:
    pusha
.loop:
    lodsb
    or al, al
    jz .done
    call draw_char_generic
    add cx, 8
    jmp .loop
.done:
    popa
    ret

draw_char_generic:
    pusha
    push ds
    mov dx, 0xF000
    mov ds, dx
    mov si, 0xFA6E
    xor ah, ah
    shl ax, 3
    add si, ax
    
    mov dx, [esp+18] ; DX from pusha stack
    mov cx, [esp+20] ; CX from pusha stack
    
    mov bh, 8 ; 8 rows
.r_loop:
    lodsb
    mov ah, 8 ; 8 bits
    push cx
.b_loop:
    test al, 0x80
    jz .skip
    push ax
    push es
    mov ax, 0xa000
    mov es, ax
    mov ax, 320
    mul dx
    add ax, cx
    mov di, ax
    mov al, bl ; Color
    mov [es:di], al
    pop es
    pop ax
.skip:
    shl al, 1
    inc cx
    dec ah
    jnz .b_loop
    pop cx
    inc dx
    dec bh
    jnz .r_loop
    pop ds
    popa
    ret

title_text db 'MS-DOS Executive', 0
menu_text  db 'File  View  Special', 0
