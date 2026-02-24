import { Injectable } from '@angular/core';
  
import { ToastrService, IndividualConfig } from 'ngx-toastr';
  

@Injectable({
  providedIn: 'root'
})
export class NotificationService {
  
  private config: Partial<IndividualConfig> = {timeOut: 3000, progressBar: true, progressAnimation: 'increasing', }

  constructor(private toastr: ToastrService) {}
  
  showSuccess(message){
    this.toastr.success(message, "Success", this.config)
    console.log("Notfication service - succcess: ", message);
  }
  
  showError(message, customTime: number = 3000){
    this.config.timeOut = customTime;
    this.toastr.error(message, "Error", this.config)
    console.log("Notfication service - error: ", message);
  }
  
  showInfo(message, customTime: number = 3000){
    this.config.timeOut = customTime;
    this.toastr.info(message, "Info", this.config)
    console.log("Notfication service - info: ", message);

  }
  
  showWarning(message, customTime: number = 3000){
    this.config.timeOut = customTime;
    this.toastr.warning(message, "", this.config)
    console.log("Notfication service - warning: ", message);
  }
  
}