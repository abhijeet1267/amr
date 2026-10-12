# Wiring review & next steps

You have the parts and you've made the connections. This is what to do next,
and exactly which photos let me check your wiring against the firmware.

---

## 0. Where you are, and what happens next

```
YOU ARE HERE  →  [ parts in hand, connections made ]
   1. photograph the wiring            ← send me these
   2. I review them against the pin map (below)
   3. fix anything flagged (usually 2 pins)
   4. flash the Arduino                → docs/setup_arduino.md
   5. set up the Raspberry Pi          → docs/DEPLOY.md Part A
   6. run tools/health_check.sh
   7. staged bring-up, wheels OFF the ground → docs/hardware.md §7
   8. put it on the floor, slowly
```

Nothing moves until step 7, and step 7 starts with the wheels off the ground.

---

## 1. Photograph these (8 shots)

Good light, in focus, and include the **board labels** in frame. A wide shot of
a whole board is more useful than a perfect close-up of one pin.

| #   | Shot                                   | What must be visible                                                                                            |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1   | **L298N, top-down, whole board**       | `IN1`–`IN4`, `ENA`/`ENB`, the `12V`/`GND`/`5V` terminals, and every wire landing on them                        |
| 2   | **ENA/ENB area, close-up**             | whether the little **jumper caps** are fitted or removed (this is the #1 cause of "motors only run full speed") |
| 3   | **Arduino UNO, top-down, whole board** | every jumper and its pin number — I need to read which pin each wire is on                                      |
| 4   | **Power terminals + battery pack**     | which battery terminal goes to `12V` and which to `GND`, and the pack's voltage (e.g. 6×AA, 2S Li-ion)          |
| 5   | **The ground path, wide**              | battery `−`, L298N `GND`, Arduino `GND` all in one frame                                                        |
| 6   | **One HC-SR04, close-up**              | `VCC`/`GND`/`Trig`/`Echo` labels and its four wires (any one sensor is enough)                                  |
| 7   | **Motor terminals**                    | each motor's two wires into `OUT1`/`OUT2` and `OUT3`/`OUT4`                                                     |
| 8   | **Camera ribbon at the Pi**            | the ribbon seated in the CSI connector, latch closed, contacts facing the right way                             |

If you can't get all 8, send what you have — 1, 2 and 3 are the important ones.

---

## 2. What I will check in them

The firmware's pins are **placeholders** (`TODO_VERIFY`) — these are the things
that actually break a build. I'll check each against your photos:

1. **ENA/ENB jumper caps removed.** If they're fitted, `ENA`/`ENB` are tied to
   the module's own 5 V and the Arduino's PWM is ignored — the motors run full
   speed no matter what you send.
2. **Motors powered from the battery pack**, never from the Pi's or the
   Arduino's 5 V rail.
3. **Common ground** between battery `−`, L298N `GND`, Arduino `GND` (and the Pi,
   through USB). A missing common ground makes the serial link flaky and the
   sensors read garbage.
4. **Arduino motor pins match the firmware** — `motor_control.h` expects:

   | Signal                  | Pin          | L298N         |
   | ----------------------- | ------------ | ------------- |
   | Left forward / reverse  | `D5` / `D4`  | `IN1` / `IN2` |
   | Left enable             | `D6`         | `ENA`         |
   | Right forward / reverse | `D10` / `D9` | `IN3` / `IN4` |
   | Right enable            | `D8`         | `ENB`         |

5. **⚠️ Conflict 1 — the rear ultrasonic collides with the left motor.** The
   firmware's rear sensor is on `D4`/`D5`, which are the _same pins_ as
   `IN2`/`IN1`. If you wired the rear sensor there, driving the left motor will
   fight the sensor. It must move (e.g. to `A1`/`A2`).
6. **⚠️ Conflict 2 — `ENB` on `D8` is not a PWM pin.** On the UNO only
   `3, 5, 6, 9, 10, 11` are PWM-capable, so `ENB=D8` gives on/off, not speed.
   Fine today (`MOTOR_PWM_ENABLED 0`), a problem the moment you want speed
   control. Move it to a PWM pin **and** re-check it doesn't clash with the
   ultrasonic pins.
7. **HC-SR04 `VCC` on 5 V** (not 3.3 V), and each sensor's `Trig`/`Echo` on two
   _different_ pins.
8. **Camera ribbon** contacts facing the correct way and the latch closed.
9. **USB cable is a data cable** — a charge-only cable cannot flash or talk.

A clean map that avoids 5 and 6 is in
[`hardware.md`](hardware.md) §5.

---

## 3. Then, in this order

**Step 1 — Flash the Arduino.** Install the toolchain, open
`firmware/arduino/amr_controller/`, board **Arduino Uno**, Upload. Verify over
the serial monitor at 9600 baud:

| Type      | Expect                        |
| --------- | ----------------------------- |
| `PING`    | `PONG`                        |
| `VERSION` | `VERSION 1.0`                 |
| `STATUS`  | `STATUS L=0 R=0 MODE=STOPPED` |

Full detail: [`setup_arduino.md`](setup_arduino.md).

**Step 2 — Get the code onto the Raspberry Pi.** Two folders side by side
(`raspberry_pi/` and `config/`), then the venv. Full detail:
[`DEPLOY.md`](DEPLOY.md) §A2–A3.

**Step 3 — Run the health check** on the Pi:

```bash
cd ~/amr && ./tools/health_check.sh
```

It checks the serial port, the firmware link, the camera and the web stack.

**Step 4 — Staged bring-up**, wheels **off the ground**:
[`hardware.md`](hardware.md) §7. Each stage has a validation; don't skip one.

**Step 5 — Only then** put it on the floor, at a crawl, with a hand on the
power switch.

---

## 4. Before you power anything

1. **Motors on the external battery pack** — never the Pi's or Arduino's 5 V.
2. **Common ground** across battery, L298N, Arduino and Pi.
3. **Wheels off the ground** for the first motion tests.
4. The **E-STOP path must be reachable** — test it before trusting the robot.
5. The web panel has **no authentication**: keep it on your LAN only.

---

## 5. When you send the photos

Send them in one message and say roughly what you'd like checked. I'll go
through each against §2 and tell you exactly what (if anything) to move before
you power it up.

> Reminder: none of this has been run on real hardware yet — yours is the first
> real build. Treat every stage as unverified until its validation passes.

**See also:** [`COMPONENTS.md`](COMPONENTS.md) (every component and connection
analysed, with the full pin table) · [`DEPLOY.md`](DEPLOY.md) ·
[`hardware.md`](hardware.md) · [`setup_arduino.md`](setup_arduino.md) ·
[`setup_raspberry_pi.md`](setup_raspberry_pi.md)
