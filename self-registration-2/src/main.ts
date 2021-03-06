import { bootstrap, module } from 'angular';
import routes from './config/routes';
import ApplicationComponent from './components/application/application.component';
import DashboardComponent from './components/dashboard/dashboard.component';
import RegistrationComponent from './components/registration/registration.component';
import UserService from './services/user.service';
import RegistrationSuccessComponent from './components/registration-success/registration-success.component';


module('app', [
    'ui.router'
])
    .config(routes)
    .component('applicationComponent', ApplicationComponent)
    .component('dashboardComponent', DashboardComponent)
    .service('userService', UserService)
    .component('registrationComponent', RegistrationComponent)
    .component('registrationSuccessComponent', RegistrationSuccessComponent);

bootstrap(document, ['app', 'ngAnimate', 'ngAria']);
