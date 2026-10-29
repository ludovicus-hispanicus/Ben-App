export interface DestitchViewBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DestitchView {
  code: string;
  bbox: DestitchViewBBox;
  origin: DestitchViewBBox;
  area: number;
  crop_base64?: string | null;
  mask_base64?: string | null;
}

export interface DestitchResult {
  views: DestitchView[];
  canvas: DestitchViewBBox;
  background: number[];
  error?: string | null;
}

export interface DestitchClassification {
  is_composite: boolean;
  view_count: number;
  confidence: number;
  error?: string | null;
}

export interface DestitchSplitRequest {
  image: string;
  include_crops?: boolean;
  include_masks?: boolean;
}

export interface DestitchSplitByPathRequest {
  path: string;
  include_crops?: boolean;
  include_masks?: boolean;
}

export interface DestitchClassifyRequest {
  image: string;
}

export interface DestitchBatchStartRequest {
  source_folder_path: string;
  destination_folder_path: string;
  passthrough_non_composites?: boolean;
  include_masks?: boolean;
  overwrite_existing?: boolean;
  include_filenames?: string[];
  exclude_filenames?: string[];
}

export interface DestitchBatchStartResponse {
  success: boolean;
  job_id?: string;
  total_images?: number;
  message?: string;
  error?: string;
}

export interface DestitchBatchResultItem {
  input: string;
  status: 'destitched' | 'passthrough' | 'passthrough_exists' | 'skipped' | string;
  output_count: number;
  outputs?: string[];
  view_codes?: string[];
}

export interface DestitchBatchFailedItem {
  input: string;
  error: string;
}

export interface DestitchBatchStatus {
  success: boolean;
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  source_folder_path: string;
  destination_folder_path: string;
  total_images: number;
  processed_images: number;
  failed_images: number;
  progress_percent: number;
  current_image: number;
  current_filename: string;
  results: DestitchBatchResultItem[];
  failed_results: DestitchBatchFailedItem[];
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string | null;
  options?: {
    passthrough_non_composites: boolean;
    include_masks: boolean;
    overwrite_existing: boolean;
  };
}

export interface DestitchBatchJobSummary {
  job_id: string;
  status: string;
  source_folder_path: string;
  destination_folder_path: string;
  total_images: number;
  processed_images: number;
  failed_images: number;
  progress_percent: number;
  created_at?: string;
  completed_at?: string;
}

export interface LocalFolderInfo {
  path: string;
  parent?: string;
  folders: Array<{ name: string; path: string; image_count: number }>;
  image_count: number;
  images?: string[];
  error?: string;
}
