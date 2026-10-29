import { Dimensions } from "./letter";

// --- Sign-level results ---

export interface CuReGuess {
    label: string;
    unicode: string;
    confidence: number;
}

export interface CuReSignResult {
    label: string;
    unicode: string;
    confidence: number;
    line: number;
    position: number;
    bbox: Dimensions;
    top3: CuReGuess[];
}

// --- API responses ---

export interface CuReClassifyResponse {
    lines: string[];
    dimensions: Dimensions[];
    signs: CuReSignResult[];
}

export interface CuReDetectResponse {
    dimensions: Dimensions[];
    line_count: number;
    sign_count: number;
}

export interface CuReCropClassifyResponse {
    predictions: CuReGuess[];
}

// --- Model management ---

export interface CuReModelInfo {
    name: string;
    created?: string;
    epochs?: number;
    accuracy?: number;
    size_mb?: number;
    is_active?: boolean;
}

export interface CuReActiveModel {
    active: boolean;
    model_name?: string;
    num_classes?: number;
    message?: string;
}

// --- Training ---

export interface CuReTrainingStatus {
    total_crops: number;
    total_labels: number;
    unique_labels: number;
    min_signs_required: number;
    is_ready: boolean;
    progress_pct: number;
}

export interface CuReTrainingProgress {
    status: 'idle' | 'preparing' | 'training' | 'completed' | 'failed' | 'cancelled';
    current_epoch: number;
    total_epochs: number;
    accuracy: number;
    val_accuracy: number;
    loss: number;
    model_name: string | null;
    error: string | null;
    started_at: string | null;
    completed_at: string | null;
    epoch_history: CuReEpochRecord[];
    best_accuracy: number;
    no_improve_count: number;
    early_stopped: boolean;
}

export interface CuReEpochRecord {
    epoch: number;
    accuracy: number;
    val_accuracy: number;
    loss: number;
}

// --- Annotation upload ---

export interface CuReAnnotationStats {
    total_crops: number;
    total_labels: number;
    unique_labels: number;
    labels_breakdown: { [label: string]: number };
}
