all: fsos.img

fsos.img: setup.asm core.asm general.asm grafic.asm
	nasm -f bin setup.asm -o fsos.bin
	# Create a 1.44MB floppy image
	dd if=/dev/zero of=fsos.img bs=512 count=2880
	# Copy the binary to the start of the image
	dd if=fsos.bin of=fsos.img conv=notrunc

run: fsos.img
	qemu-system-i386 -drive format=raw,file=fsos.img

clean:
	rm -f fsos.bin fsos.img
