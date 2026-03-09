import { Component, Input, OnInit } from '@angular/core';
import { TextIdentifiers } from 'src/app/models/cured';
import { SelectorState } from '../../smart-selector/smart-selector.component';

@Component({
  selector: 'text-identifiers',
  templateUrl: './text-identifiers.component.html',
  styleUrls: ['./text-identifiers.component.scss']
})
export class TextIdentifiersComponent implements OnInit {

  @Input() public museums: SelectorState[] = []; 
  public publications: SelectorState[] = [{value: "gordins publications"},{value: "avital pubs"}]; 

  @Input() public textIdentifiers: TextIdentifiers;


  constructor() { }

  ngOnInit(): void {
  }

}
