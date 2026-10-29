import { NgModule } from "@angular/core";
import { CommonModule } from "@angular/common";
import { MatSelectModule } from "@angular/material/select";
import { MatTooltipModule } from "@angular/material/tooltip";
import { MatProgressBarModule } from "@angular/material/progress-bar";
import { MatButtonModule } from "@angular/material/button";
import { OllamaModelPickerComponent } from "./ollama-model-picker.component";


@NgModule({
    imports: [
        CommonModule,
        MatSelectModule,
        MatTooltipModule,
        MatProgressBarModule,
        MatButtonModule
    ],
    declarations: [
        OllamaModelPickerComponent
    ],
    exports: [
        OllamaModelPickerComponent
    ],
})
export class OllamaModelPickerModule {
}
