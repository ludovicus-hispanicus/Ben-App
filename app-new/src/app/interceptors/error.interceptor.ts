import {Injectable} from '@angular/core';
import {HttpEvent, HttpInterceptor, HttpHandler, HttpRequest, HTTP_INTERCEPTORS, HttpResponse} from '@angular/common/http';
import {Observable} from 'rxjs';
import { NotificationService } from '../services/notification.service';

import {HttpErrorResponse, } from '@angular/common/http';
import { throwError} from 'rxjs';
import {catchError, map} from "rxjs/operators";

@Injectable()
export class ErrorInterceptor implements HttpInterceptor {

    constructor(private notificationService: NotificationService) {

    }

    intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
        return next.handle(request).pipe(
            catchError((error: HttpErrorResponse) => {
                let errorMsg = '';
                if (error.error instanceof ErrorEvent) {
                    console.log('This is client side error');
                    errorMsg = `Error: ${error.error.message}`;
                } else {
                    console.log('This is server side error');
                    console.log(error.error.detail);
                    errorMsg = `Server error. Details: ${error.error.detail}`;
                }
                this.notificationService.showError(`${errorMsg}`)
                return throwError(errorMsg);
            })
        )
    }
}

export const errorInterceptorProviders = [
    { provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true }
  ];