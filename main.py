# Germán Andrés Xander 2024

from machine import Pin
import asyncio
from primitives import Pushbutton

led_board = Pin("LED", Pin.OUT)
led_rojo = Pin(14, Pin.OUT)

def toggle(led):
    led.toggle()

async def boton():
    pin = Pin(28, Pin.IN, Pin.PULL_DOWN)  # Pushbutton to vcc
    pb = Pushbutton(pin)
    pb.press_func(toggle, (led_board,))  # Note how function and args are passed

async def heartbeat():
    while True:
        await asyncio.sleep_ms(500)
        led_rojo.toggle()

async def main():
    asyncio.create_task(boton())
    asyncio.create_task(heartbeat())
    n = 0
    while True:
        print(n)
        n += 1
        await asyncio.sleep(1)

asyncio.run(main())  # Run main application code
 