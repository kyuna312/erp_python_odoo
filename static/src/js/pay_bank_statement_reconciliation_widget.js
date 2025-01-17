odoo.define('ub_kontor.pay_bank_statement_reconciliation_widget', function (require) {
    var Widget = require('web.Widget');
    var widgetRegistry = require('web.widget_registry');
    var core = require('web.core');
    var rpc = require('web.rpc');
    var QWeb = core.qweb;
    var relational_fields = require("web.relational_fields");
    var fieldRegistry = require('web.field_registry');

    var reconciliation_widget =  Widget.extend({
        template: 'pay_bank_statement_reconciliation_widget',
        init: function (parent, options) {
            this._super(parent);
            this.options = options || {};
        },
        start: function () {
            result = this._super();
            this.initialize_content();
            return result
        },
        initialize_content: function(){
            var self = this;
            var parent = this.getParent();
            self.form_data = parent.state.data;
            statement_id = self.form_data.statement_id.data.id;
            var FieldMany2one = fieldRegistry.get('many2one');
             rpc.query({
                model: 'pay.bank.statement.line',
                method: 'search_read',
                domain:[['statement_id', '=', statement_id]],
                fields:['id','payment_ref', 'amount', 'datetime', 'address_id']
            }).then((statement_lines)=>{
                statement_lines.map(el=>{
                    el.amount = new Intl.NumberFormat('en-US', {
                        minimumFractionDigits: 2,  // Ensure two decimal places
                        maximumFractionDigits: 2
                    }).format(el.amount);
                })
                self.display({
                    'statement_line_list': statement_lines
                });
                statement_lines.map(el => {
                    var res_id = el.address_id && el.address_id.length > 0 ? el.address_id[0] : false;
                    new FieldMany2one(self, 'address_id', {
                        model: 'ref.address', // Target model of Many2one
                        res_id: res_id,   // Set the ID of the record
                        mode: 'readonly',     // Display mode
                        attrs: { options: { no_create: true } },
                    });

                });
            });
        },
        display: function(data){
            var $el = $(QWeb.render('pay_bank_statement_reconciliation_widget', data));
            this.$el.html($el);
        }
    });
    widgetRegistry.add('ub_kontor.pay_bank_statement_reconciliation_widget', reconciliation_widget);
    return reconciliation_widget;
});