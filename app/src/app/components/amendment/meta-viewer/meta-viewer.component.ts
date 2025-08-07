import { Component, Input, OnInit } from '@angular/core';
import { Info } from 'src/app/models/letter';

@Component({
  selector: 'meta-viewer',
  templateUrl: './meta-viewer.component.html',
  styleUrls: ['./meta-viewer.component.scss']
})
export class MetaViewerComponent implements OnInit {

  constructor() { }

  @Input() public metadata: Info[];


  ngOnInit(): void {
  }

}
