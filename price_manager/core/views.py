# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404,
                              HttpResponse,
)
from django.contrib import messages
from django.views.generic import (ListView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView,
                                  FormView,
                                  TemplateView)
from django.urls import reverse
from django.views.generic.edit import FormMixin
from django_tables2 import SingleTableView, RequestConfig

# Импорты моделей, функций, форм, таблиц
from .models import *
from .functions import *
from .forms import *
from .tables import *

# Импорты сторонних библиотек
import pandas as pd
import json


class MainPage(TemplateView):
  # model = Product
  # table_class = ProductTable
  template_name = 'core/main.html'
  def get_context_data(self, **kwargs):
    try:
      for file in FileModel.objects.all():
        file.file.delete()
        file.delete()
    except BaseException as ex:
      messages.error(self.request, 'Ничего не произошло')
    return super().get_context_data(**kwargs)

# Обработка поставщика

class SupplierList(SingleTableView):
  '''Список поставщиков на <<supplier/>>'''
  model = Supplier
  table_class = SupplierListTable
  template_name = 'supplier/list.html'

class SupplierSettingList(SingleTableView):
  '''Список Настроек на транице <<supplier/<int:id>/settings/>>'''
  model = Setting
  table_class = SettingListTable
  template_name = 'supplier/settings.html'
  def get_table_data(self):
    return Setting.objects.filter(supplier_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier_id'] = self.kwargs['id']
    context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
    return context
  
class SupplierDetail(SingleTableView):
  '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

  model = SupplierProduct
  table_class = SupplierProductListTable
  template_name = 'supplier/detail.html'
  def get_queryset(self):
    queryset = SupplierFilterForm().filter_queryset(
      super().get_queryset().filter(
      supplier_id=self.kwargs['id']),
      self.request.GET
    )
    return queryset
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier_id'] = self.kwargs['id']
    context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
    context['filter_form'] = SupplierFilterForm(self.request.GET or None)
    return context

class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  fields = '__all__'
  success_url = '/supplier'
  template_name = 'supplier/create.html'

# Обработка настройки

class SettingCreate(CreateView):
  '''Создание настроек <<supplier/<int:id>/setting/create/<int:f_id>/>>'''
  model = Setting
  form_class = SettingForm
  template_name = 'supplier/setting/create.html'
  def get_form(self, **kwargs):
    form = super().get_form(**kwargs)
    # Сетап листов и датафрейма
    self.file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    excel_file = pd.ExcelFile(self.file_model.file)
    choices = [(name, name) for name in excel_file.sheet_names]
    # Установка начальных значений
    form.fields['sheet_name'].choices = choices
    form.fields['supplier'].initial=Supplier.objects.get(id=self.kwargs['id'])
    try:
      sheet_name = form.data['sheet_name']
    except:
      sheet_name = choices[0][0]
    self.df = excel_file.parse(sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
    self.link_factory = LinkFactory(self.request.POST or None)
    if len(self.link_factory.forms) != len(self.df.columns):
      self.link_factory = LinkFactory()
      self.link_factory.extra = len(self.df.columns)
    if not self.link_factory.data == {}:
      self.mapping = {self.link_factory.data[f'form-{i}-link'] : self.df.columns[i] 
                for i in range(len(self.df.columns))
                if not self.link_factory.data[f'form-{i}-link'] == ''}
    else: self.mapping = {}
    return form
  def form_valid(self, form):
    unique = []
    for i in range(len(self.df.columns)):
      buff = self.link_factory.data[f'form-{i}-link']
      if buff in unique and buff:
        form.add_error(None, 'Не уникальные поля')
        return self.form_invalid(form)
      unique.append(buff)
    if 'article' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Артикул')
      return self.form_invalid(form)
    if 'name' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Наименование')
      return self.form_invalid(form)
    if 'priced_only' in form.data and form.data['priced_only']:
      if not 'supplier_price' in self.mapping:
        form.add_error(None, 'Не выбрано поле цены')
        return self.form_invalid(form)
      self.df = self.df[self.df[self.mapping['supplier_price']].notnull()]
    self.df = self.df[self.df[self.mapping['article']].notnull()]
    self.df = self.df[self.df[self.mapping['name']].notnull()]
    if self.request.POST.get('submit-btn') == 'apply':
      return self.form_invalid(form)
    setting = form.save()
    self.success_url = reverse('setting-upload', kwargs={'id':setting.id, 'f_id':self.file_model.id})
    for key, value in self.mapping.items():
      Link.objects.update_or_create(
        defaults={
          'setting': setting,
          'link': key
        },
        column = value
      )
    return super().form_valid(form)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['link_factory'] = self.link_factory
    widgets = [form for form in self.link_factory.forms]
    context['table'] = LinkCreateTable(df=self.df, widgets=widgets, data=self.df.to_dict('records'))
    RequestConfig(context['table'])
    return context
  def render_to_response(self, context, **response_kwargs):
    return super().render_to_response(context, **response_kwargs)
  
class SettingDetail(SingleTableView):
  '''Отображает настройку поставщика <<setting/<int:id>/>>'''
  model = Link
  table_class = LinkListTable
  template_name = 'supplier/setting/detail.html'
  def get_table_data(self):
    return Link.objects.filter(setting_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['setting_id'] = self.kwargs['id']
    context['setting'] = Link.objects.get(id=context['setting_id'])
    return context

class SettingUpload(DetailView):
  '''Проверка данных перед загрузкой <<setting/<int:id>/upload/<int:f_id>/>>'''
  model = Setting
  template_name='supplier/setting/upload.html'
  pk_url_kwarg = 'id'
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    setting = self.get_object()
    context['setting'] = setting
    context['supplier'] = setting.supplier
    file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    try:
      excel_file = pd.ExcelFile(file_model.file)
      mapping = {get_field_details(SupplierProduct)[link.link]['verbose_name']:link.column for link in Link.objects.all().filter(setting_id=setting.id)}
      links = {link.link: link.column for link in Link.objects.all().filter(setting_id=setting.id)}
      self.df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
      self.df = self.df[mapping.values()]
      if setting.priced_only:
        self.df = self.df[self.df[links['supplier_price']].notnull()]
      self.df = self.df[self.df[links['article']].notnull()]
      self.df = self.df[self.df[links['name']].notnull()]
      table = UploadListTable(mapping=mapping, data=self.df.to_dict('records'))
      RequestConfig(table)
      context['table'] = table
    except BaseException as ex:
      messages.error(self.request, ex)
      file_model.file.delete()
      file_model.delete()
    return context
  def render_to_response(self, context, **response_kwargs):
    try:
      if self.df.empty:
        return redirect('supplier')
    except:
      return redirect('supplier')
    if not 'table' in context:
      return redirect('/404')
    return super().render_to_response(context, **response_kwargs)

# Обработка файлов

class FileUpload(CreateView):
  '''
  Загрузка файла <<upload/<str:name>/<int:id>/>>
  name - url name to link after
  '''
  model = FileForm
  form_class = FileForm
  template_name = 'core/upload.html'
  def form_valid(self, form):
    f_id = form.save().id
    self.success_url = reverse(self.kwargs['name'],
                               kwargs={'id' : self.kwargs['id'], 'f_id':f_id})
    return super().form_valid(form)

# Обработка продуктов

def delete_supplier_product(request, **kwargs):
  '''
  Подвязка к функции удаления на странице поставщика
  <<supplier-product/<int:id>/delete/>>
  '''
  product = SupplierProduct.objects.get(id=kwargs['id'])
  id = product.supplier.id
  product.delete()
  return redirect('supplier-detail', id = id)
  
def upload_supplier_products(request, **kwargs):
  '''Тригер загрузки товаров <<setting/<int:id>/upload/<int:f_id>/upload/>>'''
  setting = Setting.objects.get(id=kwargs['id'])
  supplier = setting.supplier
  file_model = FileModel.objects.get(id=kwargs['f_id'])
  excel_file = pd.ExcelFile(file_model.file)
  links = {link.link: link.column for link in Link.objects.all().filter(setting_id=setting.id)}
  df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
  df = df[links.values()]
  if setting.priced_only:
    df = df[df[links['supplier_price']].notnull()]
  df = df[df[links['article']].notnull()]
  df = df[df[links['name']].notnull()]
  added_to_main = 0
  updates = 0
  creates = 0
  errors = 0
  
  for _, row in df.iterrows():
    try:
      data={}
      # Map DataFrame columns to model fields
      for model_field, df_col in links.items():
        if df_col in row and not model_field in FOREIGN and not model_field in NECESSARY:
          data[model_field] = row[df_col]
      data['currency'] = setting.currency

      kwargs = {field: row[links[field]] for field in NECESSARY if field not in FOREIGN}
      kwargs['supplier'] = supplier
      # Update or create
      product, created = SupplierProduct.objects.update_or_create(
        **kwargs,
        defaults=data
      )
      if created and setting.id_as_sku:
        sku = MainProduct.objects.create(sku=f'{product.supplier.id}-{product.article}',
                                   **kwargs)
        added_to_main += 1
        product.sku = sku
        product.save()

      if created:
        creates += 1
      else:
        updates += 1
    except BaseException as ex:
      errors += 1
      messages.error(request, ex)

  messages.success(request, f"Создано:{creates}, Обновлено: {updates}, Ошибки: {errors}, Добавлено в главный прайс: {added_to_main}")
  file_model.file.delete()
  file_model.delete()
  setting.id_as_sku= False
  setting.save()
  return redirect('supplier-detail', id=supplier.id)

# Обработка производителей

class ManufacturerList(SingleTableView):
  '''Отображение производителей <<manufacturer/>>'''
  model = Manufacturer
  table_class = ManufacturerListTable
  template_name = 'manufacturer/list.html'

class ManufacturerDetail(SingleTableView):
  '''Отображение словоря производителя <<manufacturer/<int:id>/>>'''
  model = ManufacturerDict
  table_class = ManufacturerDictListTable
  template_name = 'manufacturer/dict.html'
  def get_table_data(self):
    return ManufacturerDict.objects.filter(manufacturer_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['manufacturer_id'] = self.kwargs['id']
    context['manufacturer'] = Manufacturer.objects.get(id=context['manufacturer_id'])
    return context

class ManufacturerCreate(CreateView):
  '''Создание Производителя <<manufacturer/create/>>'''
  model = Manufacturer
  fields = '__all__'
  success_url = '/manufacturer/'
  template_name = 'manufacturer/create.html'

class ManufacturerDictCreate(CreateView):
  '''Обновление словаря Производителя <<manufacturer/<int:id>/add-alt/>>'''
  model = ManufacturerDict
  form_class = ManufacturerDictForm
  template_name = 'manufacturer/create.html'
  def get_form(self):
    form = super().get_form()
    form.fields['manufacturer'].initial = Manufacturer.objects.get(id=self.kwargs['id'])
    return form
  def get_success_url(self):
    return reverse('manufacturer-detail',kwargs={'id':self.kwargs['id']})

# Обработка валюты

class CurrencyList(SingleTableView):
  '''Отображает валюты <</currency/>>'''
  model = Currency
  table_class=CurrencyListTable
  template_name = 'currency/list.html'
  def get_table_data(self):
    return Currency.objects.exclude(name='KZT')

class CurrencyCreate(CreateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/create.html'
  def get_success_url(self):
    return '/currency/'

class CurrencyUpdate(UpdateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/update.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return '/currency/'
  
# Обработка категорий

class CategorySortSupplierProduct(FormView):
  '''Добавление товаров в категорию категорий <<category/>>'''
  model = Category
  template_name = 'category/sort.html'
  success_url = '/category/sort/'
  form_class = CategoryAddForm
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['search_form']=SortSupplierProductFilterForm(self.request.GET)
    queryset = SupplierProduct.objects.search_fields(self.request.GET)
    context['table'] = SortSupplierProductTable(queryset)
    RequestConfig(self.request).configure(context['table'])
    return context
  def form_valid(self, form):
    selected_products = self.request.POST.getlist('selected_items')
    category = form.cleaned_data['category']
    queryset = SortSupplierProductFilterForm().filter_queryset(
      SortSupplierProductFilterForm().compile(self.request.GET.get('search', '').split(' ')), self.request.GET).all()
    if selected_products and category:
      queryset.filter(pk__in=selected_products).update(category=category)
    return super().form_valid(form)
  
class CategoryList(SingleTableView):
  '''Отображение категорий <<category/>>'''
  model = Category
  table_class = CategoryListTable
  template_name = 'category/list.html'

class CategoryCreate(CreateView):
  '''Создание Категории <<category/create/>>'''
  model = Category
  fields = '__all__'
  success_url = '/category/sort/'
  template_name = 'category/create.html'

class CategoryDelete(DeleteView):
  '''Удаление Категории <<category/<<int:id>>delete/>>'''
  model = Category
  pk_url_kwarg = 'id'
  success_url = '/category/'
  template_name = 'category/confirm_delete.html'
