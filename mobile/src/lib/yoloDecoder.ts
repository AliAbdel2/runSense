import type { Detection } from './triage';

/** Decode YOLO11 TFLite output in either [1,84,N] or [1,N,84] layout. */
export function decodeYoloOutput(output: Float32Array | Uint8Array, shape: number[], frameWidth: number, frameHeight: number, frameIndex: number, confidence = 0.45): Detection[] {
  const dims = shape.length === 3 ? shape.slice(1) : shape;
  if (dims.length !== 2) return [];
  const channelsFirst = (dims[0] ?? 0) <= 128;
  const channels = channelsFirst ? dims[0] ?? 0 : dims[1] ?? 0;
  const count = channelsFirst ? dims[1] ?? 0 : dims[0] ?? 0;
  if (channels < 5) return [];
  const detections: Detection[] = [];
  for (let i = 0; i < count; i += 1) {
    const read = (channel: number) => channelsFirst ? output[channel * count + i] : output[i * channels + channel];
    const cx = Number(read(0)); const cy = Number(read(1)); const w = Number(read(2)); const h = Number(read(3));
    let bestClass = -1; let bestScore = confidence;
    for (let c = 4; c < channels; c += 1) { const score = Number(read(c)); if (score > bestScore) { bestScore = score; bestClass = c - 4; } }
    if (bestClass < 0) continue;
    const scaleX = frameWidth / 640; const scaleY = frameHeight / 640;
    detections.push({ frameIndex, trackId: i, objClass: COCO_CLASSES[bestClass] ?? `class_${bestClass}`, x1: (cx - w / 2) * scaleX, y1: (cy - h / 2) * scaleY, x2: (cx + w / 2) * scaleX, y2: (cy + h / 2) * scaleY, frameWidth, frameHeight, confidence: bestScore });
  }
  return detections;
}

export const COCO_CLASSES = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush'];
