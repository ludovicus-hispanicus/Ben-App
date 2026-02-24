import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { BrowserModule } from "@angular/platform-browser";

import { FormsModule } from "@angular/forms";
import { TextSelectorComponent } from "./text-selector.component";
import { SmartSelectorModule } from "../smart-selector/smart-selector.module";
import { MatButtonToggleModule } from "@angular/material/button-toggle";
import { MatFormFieldModule } from "@angular/material/form-field";
import { MatInputModule } from "@angular/material/input";
import { MatCardModule } from "@angular/material/card";
import { MatStepperModule } from "@angular/material/stepper";
import { MatRadioModule } from "@angular/material/radio";
import {MatDividerModule} from '@angular/material/divider';
import { TextIdentifiersComponent } from "./text-identifiers/text-identifiers.component";
import { MatTooltipModule } from "@angular/material/tooltip";


@NgModule({
    imports: [
        BrowserModule,
        MatCardModule,
        FormsModule,
        MatButtonModule,
        SmartSelectorModule,
        MatButtonToggleModule,
        MatFormFieldModule,
        MatInputModule,
        MatStepperModule,
        MatRadioModule,
        MatDividerModule,
        MatTooltipModule
    ],
    declarations: [ 
        TextSelectorComponent,
        TextIdentifiersComponent
    ],
    exports: [
        TextSelectorComponent   
    ],
    providers: [],
 })
 
 export class TextSelectorModule {
 }