import { NgModule } from "@angular/core";
import { CommonModule } from "@angular/common";
import { MatSelectModule } from "@angular/material/select";
import { MatTooltipModule } from "@angular/material/tooltip";
import { OllamaModelPickerComponent } from "./ollama-model-picker.component";


@NgModule({
    imports: [
        CommonModule,
        MatSelectModule,
        MatTooltipModule
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
