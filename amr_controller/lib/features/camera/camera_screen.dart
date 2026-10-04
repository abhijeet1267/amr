// Camera — the Raspberry Pi camera feed + vision overlays.
//
// This consumes the backend's REAL camera interface (verified in server.py):
//   GET /camera/status   -> metadata (status/source/resolution/has_frame/…)
//   GET /camera/frame    -> the latest JPEG snapshot (polled, not a stream)
//   GET /camera/overlay  -> image-space detection boxes (C13)
//
// The robot has NO continuous RTSP/MJPEG/WebRTC stream — it serves the latest
// cached frame. So this page shows a polled snapshot with honest status, and
// marks stream-only controls (record/FPS/quality) as not-supported rather than
// pretending they work.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/format.dart';
import '../../models/robot_data.dart';
import '../../providers/robot_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/status_widgets.dart';

class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key});

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen> {
  Timer? _frameTimer;

  @override
  void initState() {
    super.initState();
    _frameTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (mounted) context.read<RobotProvider>().refreshCameraFrame();
    });
  }

  @override
  void dispose() {
    _frameTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<RobotProvider>();
    final cam = provider.camera;
    final bytes = provider.cameraFrameBytes;
    final overlay = provider.cameraOverlay;
    final ovW = overlay?.imageWidth ?? 0;
    final ovH = overlay?.imageHeight ?? 0;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: SectionHeader(title: 'Live Camera'),
              ),
              if (cam != null)
                StatusPill(
                  label: cam.isLive ? 'CAMERA ONLINE' : 'CAMERA OFFLINE',
                  colour: cam.isLive ? AppPalette.ok : AppPalette.dim,
                ),
            ],
          ),
          const SizedBox(height: 8),
          // --- the frame (real snapshot, or honest empty state) ---
          AspectRatio(
            aspectRatio: 16 / 9,
            child: Container(
              decoration: BoxDecoration(
                color: AppPalette.surface,
                border: Border.all(color: AppPalette.line),
                borderRadius: BorderRadius.circular(10),
              ),
              clipBehavior: Clip.antiAlias,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (bytes != null)
                    Image.memory(
                      Uint8List.fromList(bytes),
                      fit: BoxFit.contain,
                      gaplessPlayback: true,
                    )
                  else
                    const Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.videocam_off, size: 48, color: AppPalette.dim),
                          SizedBox(height: 12),
                          Text(
                            'CAMERA OFFLINE',
                            style: TextStyle(color: AppPalette.dim),
                          ),
                        ],
                      ),
                    ),
                  // Vision overlays (image-space pixels, from the real endpoint).
                  for (final d in overlay?.detections ?? const <DetectionBox>[])
                    if (ovW > 0 && ovH > 0)
                      Positioned(
                        left: d.x / ovW,
                        top: d.y / ovH,
                        width: d.w / ovW,
                        height: d.h / ovH,
                        child: IgnorePointer(
                          child: Container(
                            decoration: BoxDecoration(
                              border: Border.all(color: AppPalette.warn, width: 2),
                              borderRadius: BorderRadius.circular(2),
                            ),
                            child: Align(
                              alignment: Alignment.topLeft,
                              child: Text(
                                '${d.label} ${d.confidence != null ? '${((d.confidence ?? 0) * 100).round()}%' : ''}',
                                style: const TextStyle(
                                  color: Colors.white,
                                  backgroundColor: AppPalette.warn,
                                  fontSize: 10,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          // --- metadata ---
          const SectionHeader(title: 'Camera'),
          KvRow(
            label: 'Status',
            value: cam?.status ?? '—',
            valueColour: cam?.isLive == true ? AppPalette.ok : AppPalette.dim,
          ),
          KvRow(
            label: 'Resolution',
            value: (cam?.width != null && cam?.height != null)
                ? '${cam?.width} × ${cam?.height}'
                : '—',
          ),
          KvRow(label: 'Format', value: cam?.format ?? '—'),
          KvRow(label: 'Frame', value: fmtIntOrDash(cam?.frameId, '')),
          KvRow(label: 'Timestamp', value: cam?.timestamp == null ? '—' : fmtClock((cam!.timestamp! * 1000).round())),
          const SizedBox(height: 12),
          const SectionHeader(title: 'Vision'),
          KvRow(label: 'Objects', value: '${overlay?.count ?? 0}'),
          KvRow(
            label: 'Resolution',
            value: (overlay?.imageWidth != null && overlay?.imageHeight != null)
                ? '${overlay?.imageWidth} × ${overlay?.imageHeight}'
                : '—',
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: () => context.read<RobotProvider>().refreshCameraFrame(),
                icon: const Icon(Icons.camera_alt, size: 16),
                label: const Text('Snapshot'),
              ),
              OutlinedButton.icon(
                onPressed: null,
                icon: const Icon(Icons.fiber_manual_record, size: 16),
                label: const Text('Record'),
              ),
              OutlinedButton.icon(
                onPressed: null,
                icon: const Icon(Icons.fullscreen, size: 16),
                label: const Text('Fullscreen'),
              ),
              OutlinedButton.icon(
                onPressed: () => context.read<RobotProvider>().refreshCameraFrame(),
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Reconnect'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Notes: the robot serves the latest cached JPEG frame (no RTSP/MJPEG/WebRTC stream), so Record/FPS/quality controls are not supported by this backend.',
            style: TextStyle(color: AppPalette.dim, fontSize: 10),
          ),
        ],
      ),
    );
  }
}