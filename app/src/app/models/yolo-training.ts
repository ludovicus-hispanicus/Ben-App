/**
 * YOLO Training Models - TypeScript interfaces for YOLO layout detection training.
 */

// ============== Enums ==============

export enum TrainingStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled'
}

// ============== Dataset Models ==============

export interface YoloClass {
  id: number;
  name: string;
}

export interface YoloAnnotation {
  class_id: number;
  x_center: number;  // Normalized 0-1
  y_center: number;  // Normalized 0-1
  width: number;     // Normalized 0-1
  height: number;    // Normalized 0-1
}

export interface DatasetCreateRequest {
  name: string;
  classes: string[];
  description?: string;
}

export interface DatasetCreateResponse {
  success: boolean;
  dataset_id: string;
  name: string;
  classes: YoloClass[];
  message: string;
}

export interface ImageUploadRequest {
  image: string;  // Base64
  filename: string;
  annotations: YoloAnnotation[];
  split: 'train' | 'val';
}

export interface ImageUploadResponse {
  success: boolean;
  image_id: string;
  filename: string;
  annotation_count: number;
  message: string;
}

export interface DatasetStats {
  dataset_id: string;
  name: string;
  classes: YoloClass[];
  total_images: number;
  train_images: number;
  val_images: number;
  total_annotations: number;
  class_distribution: { [className: string]: number };
  ready_for_training: boolean;
  issues: string[];
}

export interface DatasetListItem {
  dataset_id: string;
  name: string;
  class_count: number;
  image_count: number;
  created_at: string;
  updated_at: string;
}

// ============== Model Models ==============

export interface ModelInfo {
  model_id: string;
  name: string;
  base_model: string;
  dataset_name: string;
  classes: YoloClass[];
  metrics?: ModelMetrics;
  created_at: string;
  training_epochs: number;
  file_path: string;
  file_size_mb: number;
}

export interface ModelMetrics {
  mAP50?: number;
  'mAP50-95'?: number;
  precision?: number;
  recall?: number;
}

export interface ModelListResponse {
  success: boolean;
  models: ModelInfo[];
  base_models: string[];
}

// ============== Training Models ==============

export interface TrainingConfig {
  epochs: number;
  batch_size: number;
  image_size: number;
  patience: number;
  device: string;
  workers: number;
  flipud: number;
  fliplr: number;
  mosaic: number;
}

export const DEFAULT_TRAINING_CONFIG: TrainingConfig = {
  epochs: 100,
  batch_size: 4,
  image_size: 1024,
  patience: 20,
  device: 'auto',
  workers: 4,
  flipud: 0.0,
  fliplr: 0.0,
  mosaic: 0.0
};

export interface TrainingStartRequest {
  dataset_name: string;
  base_model: string;
  output_name: string;
  config: TrainingConfig;
}

export interface TrainingStartResponse {
  success: boolean;
  training_id: string;
  message: string;
  estimated_time?: string;
}

export interface TrainingProgress {
  training_id: string;
  status: TrainingStatus;
  current_epoch: number;
  total_epochs: number;
  progress_percent: number;
  metrics?: ModelMetrics;
  eta_seconds?: number;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

export interface TrainingStatusResponse {
  success: boolean;
  progress: TrainingProgress;
}

export interface TrainingJob {
  training_id: string;
  dataset_name: string;
  output_name: string;
  status: TrainingStatus;
  progress_percent: number;
  created_at: string;
  completed_at?: string;
}

// ============== Inference Models ==============

export interface BoundingBox {
  x: number;      // Left x (pixels)
  y: number;      // Top y (pixels)
  width: number;  // Width (pixels)
  height: number; // Height (pixels)
}

export interface Detection {
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: BoundingBox;
}

export interface PredictRequest {
  image: string;  // Base64
  model: string;
  confidence: number;
  iou: number;
}

export interface PredictResponse {
  success: boolean;
  detections: Detection[];
  model_used: string;
  processing_time_ms: number;
  image_size: { width: number; height: number };
  error?: string;
}

// ============== Health Check ==============

export interface YoloHealthResponse {
  status: 'healthy' | 'unhealthy';
  models_count?: number;
  datasets_count?: number;
  error?: string;
}

// ============== UI State Models ==============

export interface AnnotationRect {
  id: string;
  class_id: number;
  class_name: string;
  x: number;       // Pixels
  y: number;       // Pixels
  width: number;   // Pixels
  height: number;  // Pixels
  color: string;
}

export const CLASS_COLORS: { [className: string]: string } = {
  'entry': '#0000FF',
  'subentry': '#00FFFF',
  'guidewords': '#808080'
};

export function getClassColor(className: string): string {
  return CLASS_COLORS[className] || '#00FF00';
}
