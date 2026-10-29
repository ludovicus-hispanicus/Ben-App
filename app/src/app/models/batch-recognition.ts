export interface LocalFolderInfo {
  path: string;
  parent?: string;
  folders: Array<{ name: string; path: string; image_count: number }>;
  image_count: number;
  image_files?: string[];
  drives?: string[];  // Windows drive roots, e.g. "C:\\"
  error?: string;
}

export interface BatchRecognitionRequest {
  source_project_id?: string;
  source_folder_path?: string;
  include_classes?: string[];
  include_filenames?: string[];
  destination_dataset_id?: number;
  destination_folder_path?: string;
  export_images?: boolean;
  model: string;
  prompt: string;
  custom_prompt?: string;
  api_key?: string;
  sub_model?: string;
  batch_size: number;
  correction_rules?: string;
  image_scale?: number;
  target_dpi?: number;
  exclude_filenames?: string[];
  box_mode?: string;
  tiling_mode?: string;
  execution_mode?: 'live' | 'batch_api';
}

export interface BatchRecognitionResponse {
  success: boolean;
  job_id: string;
  total_images: number;
  message: string;
}

export interface BatchRecognitionResultItem {
  filename: string;
  text_id: number;
  transliteration_id: number;
  lines_count: number;
  was_tiled?: boolean;
}

export interface BatchRecognitionFailedItem {
  filename: string;
  error: string;
}

export interface DynamicBatchCategory {
  category: string;
  image_count: number;
  batch_size: number;
  tiled_count?: number;
  min_tiles?: number;
  max_tiles?: number;
  api_calls?: number;
  // Legacy fields (old batch reports)
  chunks?: number;
  inferences?: number;
  total_tiles?: number;
}

export interface BatchRecognitionStatus {
  success: boolean;
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'rate_limited'
        | 'submitting' | 'batch_submitted' | 'collecting';
  source_project_name: string;
  model: string;
  prompt: string;
  current_image: number;
  total_images: number;
  processed_images: number;
  failed_images: number;
  progress_percent: number;
  current_filename: string;
  results: BatchRecognitionResultItem[];
  failed_results: BatchRecognitionFailedItem[];
  error?: string;
  created_at?: string;
  completed_at?: string;
  started_at?: string;
  batch_size?: number;
  dynamic_report?: DynamicBatchCategory[];
  image_scale?: number;
  target_dpi?: number;
  source_project_id?: string;
  source_folder_path?: string;
  include_classes?: string[];
  destination_dataset_id?: number;
  destination_folder_path?: string;
  export_images?: boolean;
  correction_rules?: string;
  effective_model?: string;
  box_mode?: string;
  rate_limit_reached?: boolean;
  rate_limit_reset?: string;
  execution_mode?: 'live' | 'batch_api';
  provider?: string;
  provider_batch_id?: string;
  submitted_at?: string;
}

export interface ProviderModel {
  value: string;
  label: string;
  family: string;
}

/** "latest:<family>" alias — resolved server-side to the newest model at job start. */
export interface LatestModelAlias {
  value: string;
  label: string;
  family: string;
  resolves_to: string;
}

export interface ProviderModelsResponse {
  success: boolean;
  message?: string;
  models: ProviderModel[];
  latest: LatestModelAlias[];
}

/** A batch on the provider account (Gemini/Claude/OpenAI/Grok), for recovery. */
export interface ProviderBatch {
  id: string;
  state: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  status: string;           // raw provider status
  created: string;
  label: string;            // "ben-batch-ocr <job_id> <source>" where the provider stores it
  model: string;
  request_count: number | null;
  local_job_id: string | null;
  local_status: string | null;
}

export interface RecoverBatchRequest {
  model: string;
  api_key: string;
  provider_batch_ids: string[];
  source_project_id?: string;
  source_folder_path?: string;
  destination_dataset_id?: number;
  destination_folder_path?: string;
  export_images?: boolean;
  box_mode?: string;
  correction_rules?: string;
}

export interface VllmStatus {
  available: boolean;
  models: string[];
  url: string;
}

export interface BatchRecognitionJobSummary {
  job_id: string;
  status: string;
  source_project_name: string;
  model: string;
  total_images: number;
  processed_images: number;
  failed_images: number;
  progress_percent: number;
  created_at?: string;
  completed_at?: string;
}
