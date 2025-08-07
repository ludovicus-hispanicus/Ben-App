import { Dimensions } from "./letter";


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
    constructor(
        public text_id: number,
        public text_identifiers: TextIdentifiers,
        public transliterations_amount: number,
        public metadata: object[] = [],
        public last_modified: string,
        public uploader_id: string
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
                source_url: string = "") {}
}

export class CuredTransliterationPreview {
    constructor(transliteration_id: number, 
        uploader_id: string,
        last_edited: string,
        image_name: string) {}
}

export class CuredTransliterationData {
    constructor(public lines: string[], 
                public boxes: Dimensions[],
                public is_fixed: boolean) {}
}