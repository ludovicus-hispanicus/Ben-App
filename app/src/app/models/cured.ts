import { Dimensions } from "./letter";


// ── Guide Lines (bezier reading guides) ──

export interface GuideControlPoint {
  x: number;
  y: number;
  cpBefore?: { x: number; y: number };  // control handle toward previous point
  cpAfter?: { x: number; y: number };   // control handle toward next point
}

export interface GuideLineData {
  id: string;
  points: GuideControlPoint[];
  color: string;         // e.g. 'rgba(255,165,0,0.4)'
  strokeWidth: number;
}


export class TextIdentifier {
    constructor(public name: string = "",
                public number: number = null) {}
}


export class TextIdentifiers {
    constructor(public museum: TextIdentifier = new TextIdentifier(),
                public publication: TextIdentifier = new TextIdentifier(),
                public p_number: TextIdentifier = new TextIdentifier()) {}
}

export class TextPreview {
    public _thumbnailUrl: any = null;
    constructor(
        public text_id: number,
        public text_identifiers: TextIdentifiers,
        public transliterations_amount: number,
        public metadata: object[] = [],
        public last_modified: string,
        public uploader_id: string,
        public latest_transliteration_id: number = null,
        public label: string = "",
        public labels: string[] = [],
        public part: string = "",
        public is_curated: boolean = false,
        public is_curated_kraken: boolean = false,
        public is_curated_vlm: boolean = false,
        public is_reviewed: boolean = false,
        public lines_count: number = 0,
        public image_size: number = null
    ) {}
}

export class GalleryItem {
    constructor(public text_id: number,
                public transliteration_id: number,
                public text_identifiers: TextIdentifiers,
                public metadata: object[] = [],
                public uploader_id: string,
                public image_base64: string) {}
}

export class CuredSubmissionDto {
    constructor(text_id: number,
                transliteration_id: number,
                lines: string[],
                boxes: Dimensions[],
                is_fixed: boolean,
                source_url: string = "",
                guides: GuideLineData[] = []) {}
}

export class CuredTransliterationPreview {
    constructor(public transliteration_id: number,
        public uploader_id: string,
        public last_edited: string,
        public image_name: string) {}
}

export class CuredTransliterationData {
    constructor(public lines: string[],
                public boxes: Dimensions[],
                public is_fixed: boolean,
                public is_curated_kraken: boolean = false,
                public is_curated_vlm: boolean = false,
                public is_reviewed: boolean = false,
                public guides: GuideLineData[] = []) {}
}

export class DatasetPreview {
    constructor(
        public dataset_id: number,
        public name: string,
        public created_at: number,
        public parent_id: number = null,
        public text_count: number = 0,
        public curated_count: number = 0,
        public curated_lines: number = 0,
        public children_count: number = 0,
        public for_production: boolean = false
    ) {}
}
