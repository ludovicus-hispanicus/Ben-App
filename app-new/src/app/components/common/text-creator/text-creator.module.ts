import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { BrowserModule } from "@angular/platform-browser";

import { FormsModule } from "@angular/forms";
import { SmartSelectorModule } from "../smart-selector/smart-selector.module";
import { MatButtonToggleModule } from "@angular/material/button-toggle";
import { ImageDialog, TextCreatorComponent } from "./text-creator.component";
import { MatFormFieldModule } from "@angular/material/form-field";
import { MatInputModule } from "@angular/material/input";
import {MatCardModule} from '@angular/material/card';
import {MatRadioModule} from '@angular/material/radio';
import {MatStepperModule} from '@angular/material/stepper';
import { TextSelectorModule } from "../text-selector/text-selector.module";
import {MatTableModule} from '@angular/material/table';
import { MatIconModule } from "@angular/material/icon";
import {MatDialogModule} from '@angular/material/dialog';
import { CommonModule } from "@angular/common";

@NgModule({
    imports: [
        CommonModule,
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
        TextSelectorModule,
        MatTableModule,
        MatIconModule,
        MatDialogModule
    ],
    declarations: [ 
        TextCreatorComponent, ImageDialog
    ],
    exports: [
        TextCreatorComponent,
        ImageDialog 
    ],
    providers: [],
 })
 
 export class TextCreatorModule {
 }