import { NgModule } from "@angular/core";
import { FormsModule, ReactiveFormsModule } from "@angular/forms";
import { MatAutocompleteModule } from "@angular/material/autocomplete";
import { MatButtonModule } from "@angular/material/button";
import { MatOptionModule } from "@angular/material/core";
import { MatInputModule } from "@angular/material/input";
import { MatSelectModule } from "@angular/material/select";
import { MatTooltipModule } from "@angular/material/tooltip";
import { BrowserModule } from "@angular/platform-browser";
import { SmartSelectorComponent } from "./smart-selector.component";


@NgModule({
    imports: [
        BrowserModule,
        MatSelectModule,
        ReactiveFormsModule,
        MatOptionModule,
        MatInputModule,
        MatAutocompleteModule,
        FormsModule,
        MatButtonModule,
        MatTooltipModule
    ],
    declarations: [ 
        SmartSelectorComponent
    ],
    exports: [
        SmartSelectorComponent   
    ],
    providers: [],
 })
 
 export class SmartSelectorModule {
 }