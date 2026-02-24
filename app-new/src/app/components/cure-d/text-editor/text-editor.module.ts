import { NgModule } from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { MatIconModule } from "@angular/material/icon";
import { MatTooltipModule } from "@angular/material/tooltip";
import { TextEditorComponent } from "./text-editor.component";

@NgModule({
    imports: [
        CommonModule,
        FormsModule,
        MatIconModule,
        MatTooltipModule,
    ],
    declarations: [
        TextEditorComponent,
    ],
    exports: [
        TextEditorComponent,
    ],
})
export class TextEditorModule {}
