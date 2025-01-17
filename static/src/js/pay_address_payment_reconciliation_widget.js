odoo.define('ub_kontor.pay_address_payment_reconciliation_widget', function (require) {
    var Widget = require('web.Widget');
    var widgetRegistry = require('web.widget_registry');
    var core = require('web.core');
    var rpc = require('web.rpc');
    var QWeb = core.qweb;

    var reconciliation_widget =  Widget.extend({
        template: 'pay_address_payment_reconciliation_widget',
         events: {
             'click .kontor_reconcile': '_onClickReconcile',
         },
         _onClickReconcile: function (event){
            invoice_id = event.target.getAttribute('data');
            payment_id = this.form_data.id;
            rpc.query({
                model: 'pay.address.payment',
                method: 'register_invoices',
                args: [[payment_id], [parseInt(invoice_id)]],
            }).then((result)=>{
                this.trigger_up('reload', { keepChanges: false });
            });
         },
        init: function (parent, options) {
            this._super(parent);
            this.options = options || {};
            var parent = this.getParent();

            parent.on('field_changed', this, function (event) {
                address_id = event.data.changes.address_id;
                if(address_id != undefined){
                    if(this.form_data.id != undefined && this.form_data.id != false){
                        rpc.query({
                            model: 'pay.address.payment',
                            method: 'write',
                            args: [[parent.state.res_id], {'address_id': address_id.id}],
                        }).then((result)=>{
                              rpc.query({
                                  model: 'pay.address.payment',
                                  method: 'compute_name',
                                  args: [[parent.state.res_id]],
                              })
                            this.initialize_content(address_id.id);
                        });
                    }
                    else{
                        this.initialize_content(address_id.id);
                    }


                }
            });
//            this.field_manager.on("field_changed:address_id", this, function(){alert("dasdsaf")});
        },
        initialize_content: function(address_id=undefined){
            var self = this;
            var parent = this.getParent();
            self.form_data = parent.state.data;
            total_residual = 0.0
            if(self.form_data.address_id.data == undefined && address_id == undefined){
                return result
            }
            if(address_id == undefined){
                address_id = self.form_data.address_id.data.id;
            }
            rpc.query({
                model: 'pay.receipt.address.invoice',
                method: 'search_read',
                domain:[['address_id', '=', parseInt(address_id)], ['payment_state', '!=', 'paid'], ['state', '=', 'posted']],
                fields:['id','name', 'amount_residual']
            }).then((invoice_list)=>{

                invoice_list.map(el=>{
                    total_residual += el.amount_residual;
                    el.amount_residual = new Intl.NumberFormat('en-US', {
                        minimumFractionDigits: 2,  // Ensure two decimal places
                        maximumFractionDigits: 2
                    }).format(el.amount_residual);

                })
                total_residual = new Intl.NumberFormat('en-US', {
                    minimumFractionDigits: 2,  // Ensure two decimal places
                    maximumFractionDigits: 2
                }).format(total_residual);
                self.display({
                    invoice_list: invoice_list,
                    show_button: self.form_data.state == 'done'||self.form_data.id == undefined||self.form_data.id == false||self.form_data.id == null? false : true,
                    total_residual: total_residual
                });
            });
        },
        start: function () {
            result = this._super();
            this.initialize_content();
            return result
        },
        display: function(data){
            var $el = $(QWeb.render('pay_address_payment_reconciliation_widget', data));
            this.$el.html($el);
        }
    });
    widgetRegistry.add('ub_kontor.pay_address_payment_reconciliation_widget', reconciliation_widget);
    return reconciliation_widget;
});