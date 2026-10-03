// A pointer-driven virtual joystick.
//
// The control metaphor: drag from the centre in any direction, and a dead-zone
// swallows small jitters so a resting finger does not send constant commands.
// Beyond the dead-zone the direction is quantised to the eight nearest
// compass sectors; the magnitude (0..1) sets the motor speed. The parent gets
// a single onCommand(direction, normalizedMagnitude) callback and never has to
// know about gesture coordinates.
//
// The child is the *visual* knob; the widget also paints the compass ring it
// sits on.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/theme.dart';

/// The eight directions this joystick can emit, mapped by the teleop screen
/// onto the robot's real `/command` verbs.
enum JoystickDirection {
  forward,
  forwardLeft,
  forwardRight,
  left,
  right,
  backward,
  backwardLeft,
  backwardRight,
  stop,
}

class JoystickWidget extends StatefulWidget {
  const JoystickWidget({
    super.key,
    required this.onCommand,
    this.size = 220,
    this.deadZone = 0.15,
  });

  final void Function(JoystickDirection direction, double magnitude) onCommand;

  /// The on-screen diameter of the whole control, in logical pixels.
  final double size;

  /// Fraction of the radius ignored near the centre (0..1) before a direction
  /// is considered a real command rather than a jitter.
  final double deadZone;

  @override
  State<JoystickWidget> createState() => _JoystickWidgetState();
}

class _JoystickWidgetState extends State<JoystickWidget> {
  Offset _knob = Offset.zero; // relative to centre, in logical px
  bool _active = false;

  double get _radius => widget.size / 2;

  void _handleDrag(Offset local) {
    final centre = Offset(_radius, _radius);
    final delta = local - centre;
    var distance = delta.distance;
    final r = _radius - 18; // visible knob travel radius (inside the ring)
    if (distance > r) {
      // Clamp to the ring so a fast flick doesn't look like it escaped.
      distance = r;
    }
    final dir = distance < 1e-6
        ? Offset.zero
        : delta / delta.distance * distance;

    setState(() {
      _knob = dir;
      _active = distance >= _radius * widget.deadZone;
    });

    if (!_active) {
      widget.onCommand(JoystickDirection.stop, 0);
      return;
    }

    final angleDeg = math.atan2(delta.dy, delta.dx) * 180 / math.pi;
    final direction = _quantise(angleDeg);
    final magnitude = ((distance - _radius * widget.deadZone) /
            (_radius - _radius * widget.deadZone))
        .clamp(0.0, 1.0);
    widget.onCommand(direction, magnitude);
  }

  JoystickDirection _quantise(double angle) {
    // Screen coords: +x is right, +y is DOWN, so atan2(dy, dx) is 0° at +x,
    // +90° at +y (down), -90° at -y (up). We want the robot's view, where
    // "forward" is up (-90°) and "left/right" are -180/+0 and +0 respectively.
    // The eight sectors are fixed 45° wedges; left spans the wrap point.
    var a = angle.clamp(-180.0, 180.0);
    const sectors = [
      // [min, max) -> direction
      (-112.5, -67.5, JoystickDirection.forward),
      (-157.5, -112.5, JoystickDirection.forwardLeft),
      (-67.5, -22.5, JoystickDirection.forwardRight),
      (-22.5, 22.5, JoystickDirection.right),
      (22.5, 67.5, JoystickDirection.backwardRight),
      (67.5, 112.5, JoystickDirection.backward),
      (112.5, 157.5, JoystickDirection.backwardLeft),
    ];
    for (final s in sectors) {
      if (a >= s.$1 && a < s.$2) return s.$3;
    }
    // The wrap-around sector for left: (-180, -157.5] U [157.5, 180).
    return JoystickDirection.left;
  }

  void _endDrag() {
    setState(() {
      _knob = Offset.zero;
      _active = false;
    });
    widget.onCommand(JoystickDirection.stop, 0);
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onPanDown: (d) => _handleDrag(d.localPosition),
      onPanUpdate: (d) => _handleDrag(d.localPosition),
      onPanEnd: (_) => _endDrag(),
      onPanCancel: _endDrag,
      child: SizedBox(
        width: widget.size,
        height: widget.size,
        child: Stack(
          alignment: Alignment.center,
          children: [
            // Ring.
            Positioned.fill(
              child: CustomPaint(painter: _RingPainter()),
            ),
            // Knob.
            Transform.translate(
              offset: _knob,
              child: Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _active ? AppPalette.accent : AppPalette.surfaceVariant,
                  border: Border.all(color: AppPalette.accent, width: 2),
                  boxShadow: const [
                    BoxShadow(color: Color(0x33000000), blurRadius: 8, offset: Offset(0, 2)),
                  ],
                ),
                child: const Icon(Icons.precision_manufacturing, color: AppPalette.text, size: 24),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final centre = size.center(Offset.zero);
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = AppPalette.line;
    canvas.drawCircle(centre, size.width / 2 - 1, paint);

    final radial = Paint()
      ..color = AppPalette.line.withValues(alpha: 0.6)
      ..strokeWidth = 1;
    for (var i = 0; i < 8; i++) {
      final a = i * math.pi / 4;
      final outer = Offset(centre.dx + math.cos(a) * (size.width / 2 - 10),
          centre.dy + math.sin(a) * (size.width / 2 - 10));
      canvas.drawLine(centre, outer, radial);
    }
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => false;
}