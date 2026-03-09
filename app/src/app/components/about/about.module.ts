
import { MatButtonModule } from "@angular/material/button";
import { MatCheckboxModule } from "@angular/material/checkbox";
import { MatFormFieldModule } from "@angular/material/form-field";
import { MatIconModule } from "@angular/material/icon";
import { MatInputModule } from "@angular/material/input";
import { MatTooltipModule } from "@angular/material/tooltip";
import { BrowserModule } from "@angular/platform-browser";
import { NgModule } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { SmartSelectorModule } from "../common/smart-selector/smart-selector.module";
import { MatDialogModule } from "@angular/material/dialog";
import { TextCreatorModule } from "../common/text-creator/text-creator.module";
import { MatOptionModule } from "@angular/material/core";
import { MatSelectModule } from "@angular/material/select";
import { AboutComponent } from "./about.component";
import { MarkdownModule } from "ngx-markdown";

@NgModule({
    imports: [
        BrowserModule,
        MatButtonModule,
        MatFormFieldModule,
        MatInputModule,
        MatOptionModule,
        MatCheckboxModule,
        MatSelectModule,
        MatIconModule,
        MatTooltipModule,
        FormsModule,
        SmartSelectorModule,
        MatDialogModule,
        TextCreatorModule,
        MarkdownModule.forRoot()
        ],
    declarations: [AboutComponent],
    exports: [],
    providers: [],
 })
 
 export class AboutModule {
 }