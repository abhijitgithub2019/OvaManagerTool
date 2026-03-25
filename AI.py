print("Abhijit is learning python")
n ="Abhi"
d =12
print(f"My name is {n} and age is {d}")
if d > 10:
    print("Age is more")
elif d ==10:
    print("Same age")
else :
    print("under age")



nums =[1,2,3,4,5]
for item in nums:
    print(f"item is {item}")


for index, item in enumerate(nums):
    print(index, item)


squares = [n*n for n in nums]
print(squares)
nums1 = [n for n in nums if n%2==0]
print(nums1)


