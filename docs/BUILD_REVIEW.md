# Build review — what your photos show

A review of the 10 photos supplied (`IMG_0618.pdf`) against what this project
expects. Read this before powering anything up.

> Where I could not see something clearly, it says so rather than guessing.

---

## 1. What the photos show

| Photo | What it is |
| --- | --- |
| 1 | A small **USB-A dongle with a cap** (flash drive / card reader class). Not part of the robot. |
| 2 | The **chassis** top-down: black frame, 4 yellow wheels, **2× HC-SR04** ultrasonic sensors, the **red L298N**. |
| 3 | A **green I²C module in an anti-static bag** — silkscreen reads `HW-61`, with `SDA`/`SCL`, `VCC`/`GND` and `A0`/`A1`/`A2` address pins. |
| 4 | The **Raspberry Pi 5** with its **active cooler** (heatsink + fan) and the Pi 5 documentation booklet. |
| 5 | The **L298N mounted on the chassis** — green power terminal, blue motor/power terminal, jumper caps, loose wiring. |
| 6 | The **Pi in its official red/white case**, robot in the background (background is out of focus). |
| 7 | **Cables**: a white USB cable and a **blue braided USB-A → Micro-USB** cable. |
| 8 | **Full top-down of the robot**: L298N, two front sensors, a breadboard carrying the wiring. |
| 9, 10 | Close-ups of an **HC-SR04** plugged into the breadboard with jumper wires. |

---

## 2. Check against the project's design

| Component the project expects | In your photos | Status |
| --- | --- | --- |
| Raspberry Pi (any 4/5) | **Pi 5** + active cooler, cased | ✅ present |
| Arduino **UNO** (firmware target) | **not clearly visible** — a blue board is cut off at the top of photo 8 | ⚠️ **must confirm** |
| L298N H-bridge | red module, mounted, motors connected | ✅ present |
| 2× DC gear motors | 4-wheel chassis, motors under the frame | ✅ present |
| **4×** HC-SR04 (front/left/right/rear) | **2 visible**, both at the front | ⚠️ **2 short** |
| Motor battery pack | not visible in any photo | ⚠️ **must confirm** |
| Raspberry Pi Camera + ribbon | not visible | ❌ not shown |
| I²C module (`HW-61`) | present, in a bag | ➖ **not used** by this firmware |
| USB-A → Micro-USB cable | present | ⚠️ **wrong plug for an UNO** |

---

## 3. Findings

### ⚠️ 1. I cannot see your microcontroller board

This is the one thing everything else depends on. The firmware is written for an
**Arduino UNO** — 14 digital pins, `D2`–`D13`. If your board is a **Nano**, an
**ESP32** or a **Pico**, the pin map, the PWM pins and the upload steps are all
different.

The only candidate is a **blue board at the very top of photo 8, cut off by the
frame**.

**Send me:** a straight-on, well-lit photo of that board — top side and bottom
side if you can — showing the **chip markings**.

### ⚠️ 2. Those cables will not fit an Arduino UNO

Photo 7 shows **USB-A → Micro-USB**. An UNO's socket is **USB-B** (the square
one). So either:

- your board is **not an UNO** (Nano clones are usually Micro-USB — which would
  explain the cables), or
- you are **missing the UNO's USB-B cable**.

Either way, resolve this with finding 1 before anything else — you cannot flash
or connect the board without the right cable.

### ⚠️ 3. You have 2 ultrasonic sensors; the design uses 4

I can see two, both mounted at the **front**. The firmware defines **front,
left, right and rear** (`ultrasonic.h`), and the Layer-1 proximity stop reads all
four. With two, you get front-only protection and two `-1` (no-echo) directions.

Two is a **fine starting point** — see "Next actions" for how to run with two.

### ⚠️ 4. There is a loose jumper wire on the L298N

In photo 5 a **single black wire with a female header is hanging free**, not
seated on a pin. On these modules that is usually an `ENA`/`ENB` signal lead or
a `5V`/`GND` link. An unseated wire means one channel gets no enable signal and
that wheel will not turn.

**Check:** every lead is fully seated, and nothing is left dangling.

### ⚠️ 5. Check the L298N jumper caps (ENA/ENB)

Photo 5 shows **yellow jumper caps** on the module. On the L298N, the `ENA`/`ENB`
caps tie the enable pins to the module's own 5 V — **while fitted, the Arduino's
PWM is ignored and the motor only ever runs at full speed**.

That is harmless today (`MOTOR_PWM_ENABLED 0`), but remove them the moment you
want speed control, and note the finding below.

### ⚠️ 6. Where do the L298N's power wires go?

The green terminal has **black, green and red** wires leaving it. I cannot see
where they end. This must be a **separate battery pack**, never the Pi's or the
Arduino's 5 V rail.

**Check:** trace them and confirm. Then confirm a **common ground** exists
between the battery `−`, the L298N `GND` and the Arduino `GND`.

### 🔴 7. The two firmware pin faults still apply to your build

From [`COMPONENTS.md`](COMPONENTS.md):

- **`D4`/`D5` are double-booked** — `IN1`/`IN2` (left motor) share pins with the
  rear ultrasonic. Harmless while you have no rear sensor; a fault the moment you
  add one.
- **`ENB = D8` is not a PWM pin**, so the right wheel can never be speed
  controlled as configured.

Neither blocks you today. Fix both before you add the rear sensor or enable PWM.

### ➖ 8. The `HW-61` I²C module is not used

Nothing in this firmware or config touches I²C. You can leave it in the bag.

---

## 4. What I still need to see

1. **The microcontroller board** — top-down, chip markings legible. *(blocking)*
2. **The L298N's power wiring** — wide shot following the black/green/red wires
   to their source, plus the battery.
3. **The signal wires at the Arduino end** — a top-down of the board with the
   jumper wires in place, so I can read which pin each one lands on.

With those three I can give you an exact pin-by-pin verdict.

---

## 5. Next actions, in order

1. **Identify the board** (photo 1 above) and get the **correct USB cable** for
   it. Nothing else can proceed until the board is known.
2. **Seat the loose jumper** and re-check every connection on the L298N.
3. **Confirm the motor power source** is a battery pack, with a common ground.
4. **Check the ENA/ENB jumper caps** — leave them for now, remove them when you
   enable PWM.
5. **Flash the firmware** — but first set the pins to match **your** board and
   the **two** sensors you have:
   - in `firmware/arduino/amr_controller/ultrasonic.h`, disable the left/right/
     rear sensors or move their pins to unused ones, so they do not fight the
     motor pins;
   - set `ULTRASONIC_ENABLED 1` so `SENSOR` actually reports distances.
6. Then follow [`DEPLOY.md`](DEPLOY.md) → [`WIRING_CHECK.md`](WIRING_CHECK.md) →
   [`hardware.md`](hardware.md) §7, **wheels off the ground**.

---

## 6. The honest summary

Your **mechanical build is real and looks assembled** — chassis, wheels, motors,
L298N mounted, sensors mounted, wiring routed. That is further than "parts in a
box".

But three things must be settled before it moves: **which board you actually
have**, **the correct USB cable for it**, and **where the motor power comes
from**. Everything else is a smaller correction.

**See also:** [`COMPONENTS.md`](COMPONENTS.md) · [`WIRING_CHECK.md`](WIRING_CHECK.md) ·
[`DEPLOY.md`](DEPLOY.md) · [`hardware.md`](hardware.md)
