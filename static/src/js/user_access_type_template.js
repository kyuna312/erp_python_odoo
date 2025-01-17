//define the odoo.define method

odoo.define('ub_kontor.access_type_systray', function (require) {
   "use strict";
   var core = require('web.core');
   var QWeb = core.qweb;
   var Widget = require('web.Widget');
   var SystrayMenu = require('web.SystrayMenu');
   var rpc = require('web.rpc');
   var session = require('web.session');
   var access_type_systray_main = Widget.extend({
       template: 'access_type_systray_main',

       sequence: 5,
       start: function () {
           rpc.query({
               model: 'res.users',
               method: 'get_access_type_template_data',
               args: [[session.uid]],
           })
           .then((result) => {
               if (result){
                    this._renderTemplate(result);
               }
           });
           return this._super.apply(this, arguments);
       },
       _renderTemplate: function (data) {
           var $el = $(QWeb.render('access_type_systray', {
                'data': data,
           }));

           this.$el.html($el);
           this.$('.access_type').on('click', this._onclickAccessType)
       },
       _onclickAccessType: function (event) {
          event.stopPropagation();
          rpc.query({
              model: 'res.users',
              method: 'change_access_type',
              args: [[session.uid], { 'access_type': event.currentTarget.getAttribute('value') }]
          })
          location.reload();
       },
   });

   SystrayMenu.Items.push(access_type_systray_main);

   return access_type_systray_main;
});