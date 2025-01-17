odoo.define('ub_kontor.CustomListRenderer', function (require) {
    "use strict";

    var ListRenderer = require('web.ListRenderer');
    var ListController = require('web.ListController');
    ListRenderer.include({

        events: _.extend({}, ListRenderer.prototype.events, {
            'click .group_selector': 'onClickGroupSelector'
        }),


        init(parent, state, params) {

            this._super(...arguments);
        },

        onClickGroupSelector: function(event){
           var group = $(event.currentTarget).data('group');
            if (group.count) {
                group.limit = group.count;
                group.groupsLimit = group.count;
                if(!group.isOpen){
                    this.trigger_up('load', {
                        id: group.id,
                        limit: group.count,
                        offset: 0,
                        on_success: reloadedGroup => {
                             reloadedGroup.isOpen = true;
                            Object.assign(group, reloadedGroup);
                            this._render().then(function () {
                                var element = $("#"+group.id.replaceAll(".","_"));
                                if(element.length > 0){
                                    element.data('group', reloadedGroup)
                                    element = element[0]
                                    element.setAttribute("checked",true)
                                    element.offsetParent.parentElement.setAttribute('class','o_group_open')
                                    if(element.offsetParent.parentElement.classList.contains('o_group_open')){
                                        const $recordSelector = $(element.offsetParent.parentElement.parentElement.nextSibling).find('input[type=checkbox]:not(":disabled").custom-control-input');
                                        $recordSelector.prop('checked', !$recordSelector.prop("checked"));
                                        $recordSelector.change();
                                        const $sub_groups = $(element.offsetParent.parentElement.parentElement.nextSibling).find(".group_selector");
                                        if($sub_groups.length > 0){
                                            $sub_groups.click()
                                        }

                                    }
                                }
                            });;
                        },
                    });
                }else{
                    group.isOpen = false;
                    $(event.currentTarget).data('group',group)
                     this.trigger_up('toggle_group', {
                        group: group,
                        onSuccess: () => {
                            this._updateSelection();
                            if (document.activeElement.tagName === 'BODY') {
                                var groupHeaders = $('tr.o_group_header:data("group")');
                                var header = groupHeaders.filter(function () {

                                    return $(this).data('group').id === group.id;
                                });
                                header.find('.o_group_name').focus()
                            }
                        }
                     })
                }
//                this.trigger_up('toggle_group', {
//                    group: group,
//                    limit: group.count,
//                    groupsLimit: group.count,
//                    onSuccess: () => {
//                        this._updateSelection();
//                        // Refocus the header after re-render unless the user
//                        // already focused something else by now
//                        if (document.activeElement.tagName === 'BODY') {
//                            var groupHeaders = $('tr.o_group_header:data("group")');
//                            var header = groupHeaders.filter(function () {
//
//                                return $(this).data('group').id === group.id;
//                            });
//                            header.find('.o_group_name').focus();
//                            var element = $("#"+group.id.replace(".","_"))
//                            if(element.length > 0){
////                                element.attr("checked", true)
//                                event.target = element[0]
//                                if(event.target.offsetParent.parentElement.classList.contains('o_group_open')){
//                                    const $recordSelector = $(event.target.offsetParent.parentElement.parentElement.nextSibling).find('input[type=checkbox]:not(":disabled")');
//                                    $recordSelector.prop('checked', !$recordSelector.prop("checked"));
//                                    $recordSelector.change(); // s.t. th and td checkbox cases are handled by their own handler
//                                }
//                            }
//                        }
//                    },
//                });
            }

            event.stopPropagation();
        },
        _renderGroupRow: function (group, groupLevel) {
            var $row =  this._super(group, groupLevel);
            var $checkbox = $("<input>").attr("type","checkbox").addClass('group_selector').data('group', group).attr("id", group.id.replaceAll(".","_"))
            $row.find(".o_group_name").prepend($checkbox)
//            console.log()
            return $row;
        },
    })

});