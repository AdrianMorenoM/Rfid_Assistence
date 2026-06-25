from mfrc522 import MFRC522
import time

r = MFRC522()

print("Acerca tarjeta...")

while True:
    status, _ = r.MFRC522_Request(r.PICC_REQIDL)

    if status == r.MI_OK:
        status, uid = r.MFRC522_Anticoll()

        if status == r.MI_OK:
            print("UID:", uid)
            break

    time.sleep(0.2)
