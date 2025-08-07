import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { MatDialogModule } from "@angular/material/dialog";
import { DemoDialogContentComponent } from "./demo-dialog-content.component";


@NgModule({
    imports: [
        MatDialogModule,
        MatButtonModule,
    ],
    declarations: [ 
        DemoDialogContentComponent
    ],
    exports: [
        DemoDialogContentComponent
    ],
    providers: [],
 })
 
 export class DemoDialogContentModule {
 }