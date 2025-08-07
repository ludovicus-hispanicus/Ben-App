import { Rect } from "fabric/fabric-impl";
import { SignData } from "../components/amendment/letter-viewer/letter-viewer.component";

export class StageOne {
    constructor(public text_id: string,
                public transliteration: Letter[][],
                public akkademia: string[],
                public dimensions: Dimensions[][],
                public metadata: Object[],
                public is_fixed: boolean) {}
}

export class CuredResult {
    constructor(public lines: string[],
                public dimensions: Dimensions[]){}
}

export class Predictions {
    constructor(public predictions: Letter[][],
                public sign_translation: string[]) {}
}

export class AmendmentStats {
    constructor(public completed_texts: number,
                public saved_signs: number) {}
}

export class RectData {
    constructor(public index: Index,
                public selectedForAction: boolean = false) {}
}

export class Index {
    constructor(public row: number,
                public col: number) {}

    update(newIndex: Index) {
        this.row = newIndex.row;
        this.col = newIndex.col;
    }
}

export class LineError {
    constructor(public index: number,
                public boxes: number,
                public letters: number,
                public emptyLetters: number) {}
}

export class LineStats {
    constructor(public topAvg: number,
                public bottomAvg: number,
                public endLeft: number,
                public index: number) {}
}

export class Info {
    constructor(public title: string,
                public text: string) {}
}

export class Item {
    //Fields 
    
    constructor(public letter: Letter,
                public dimensions?: Dimensions,
                public imageUrl?: string,
                public id?: number) {}
                //Math.floor(Math.random() * 10000000

}

export class Prediction {
    constructor(public letter: Letter,
                public all_letters: string,
                public probability: number) {}
}

export class User {
    constructor(public name: string = "",
                public email: string = "",
                public admin: boolean = false) {}
}

export class LoginResult {
    constructor(public token: string,
                public user: User) {}
}

export class LetterHover {
    constructor(public letterIndex: Index,
                public active: boolean,
                public event: any = null) {}
}

export class Letter {
    constructor(public letter: string,
                public symbol: string = "NONE",
                public highlight: boolean = false,
                public wrong: boolean = false,
                public right: boolean = false,
                public selected: boolean = false,
                public loading: boolean = false,
                public certainty: string = "",
                public dimensions?: Dimensions,
                public predictions?: Prediction[],
                public index?: Index) {}

    public update(letterData: SignData) {
        this.letter = letterData.letter;
        this.symbol = letterData.symbol;
    }

}

export class LetterView {
    constructor(public imageData: string = "",
        public dimensions?: Dimensions) {}
}

export class LetterDto {
    constructor(public letter: string = "",
                public symbol: string = "NONE",
                public certainty: string = "",
                public dimensions: Dimensions = null,
    ) {}

    static fromLetter(letter: Letter) {
        return new LetterDto(letter.letter,
            letter.symbol,
            letter.certainty,
            letter.dimensions,);
    }
}

export class SignsData {
    constructor(public label_to_unicode: Map<string, string>,
                public unicode_to_labels: Map<string, string[]>) {}
}



export class Dimensions {
    constructor(public x: number,
                public y: number,
                public height: number,
                public width: number,
                public index?: Index) {}

    static fromRect(rect: Rect) {
        let RECT_STROKE_WIDTH = 1;
        const x = rect.left,
        y = rect.top,
        height = rect.getScaledHeight() - RECT_STROKE_WIDTH,
        width = rect.getScaledWidth();

        return new Dimensions(x, y, height, width);
    }
    
}