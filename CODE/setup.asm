[org 0x7c00]

start:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7c00

    mov [boot_drive], dl

    ; Режим 13h (320x200, 256 цветов)
    mov ax, 0x0013
    int 0x10

    ; Заливка фона (Cyan)
    mov ax, 0xa000
    mov es, ax
    xor di, di
    mov cx, 32000
    mov ax, 0x0303
    rep stosw

    ; Рисуем белое окно MS-DOS Executive
    mov dx, 20
.draw_window:
    mov ax, dx
    mov bx, 320
    mul bx
    add ax, 20
    mov di, ax
    mov cx, 280
    mov al, 15
    rep stosb
    inc dx
    cmp dx, 180
    jne .draw_window

    ; Заголовок окна (Синяя полоса)
    mov dx, 20
.title_bar:
    mov ax, dx
    mov bx, 320
    mul bx
    add ax, 20
    mov di, ax
    mov cx, 280
    mov al, 1
    rep stosb
    inc dx
    cmp dx, 32
    jne .title_bar

    ; Текст через BIOS
    mov ah, 0x02
    mov bh, 0
    mov dh, 3
    mov dl, 10
    int 0x10
    
    mov si, title_msg
    call print_string

    ; --- ИНИЦИАЛИЗАЦИЯ МЫШИ ---
    xor ax, ax
    int 0x33
    
    mov ax, 1
    int 0x33

    ; Сохраняем старые координаты
    mov word [old_mouse_x], 160
    mov word [old_mouse_y], 100

.main_loop:
    ; Опрос мыши
    mov ax, 3
    int 0x33 ; CX=X, DX=Y
    shr cx, 1 ; X / 2 для режима 13h
    
    ; Программная отрисовка курсора (на случай если BIOS не показывает)
    ; Рисуем маленькую черную точку в текущих координатах
    ; (Это гарантирует, что мы увидим движение, даже если драйвер мыши в QEMU капризничает)
    
    push cx
    push dx
    
    ; Стираем старую точку (возвращаем цвет из памяти или просто белым/синим)
    ; Для простоты просто рисуем новую. В реальной ОС нужно сохранять фон.
    
    mov ax, dx
    mov bx, 320
    mul bx
    add ax, cx
    mov di, ax
    mov al, 0 ; Черный курсор
    mov [es:di], al
    mov [es:di+1], al
    mov [es:di+320], al
    
    pop dx
    pop cx

    ; Задержка
    mov ax, 0x0FFF
.delay:
    dec ax
    jnz .delay
    
    jmp .main_loop

print_string:
    mov ah, 0x0e
.loop:
    lodsb
    or al, al
    jz .done
    int 0x10
    jmp .loop
.done:
    ret

title_msg db 'MS-DOS Executive', 0
boot_drive db 0
old_mouse_x dw 0
old_mouse_y dw 0

times 510-($-$$) db 0
dw 0xaa55
